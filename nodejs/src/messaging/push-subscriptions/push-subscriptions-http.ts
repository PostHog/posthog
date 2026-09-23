import { IncomingMessage, ServerResponse } from 'http'
import { Counter, Histogram } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { MAX_BODY_BYTES, PushSubscriptionsService } from './push-subscriptions.service'

/** Names match what Django exposes, so its dashboards and alerts survive a cutover. prometheus_client
 * appends `_total` in the exposition format and prom-client does not, hence the explicit suffix. */
const rejectionCounter = new Counter({
    name: 'push_subscription_rejection_total',
    help: 'Device registration requests rejected, by reason and HTTP method.',
    labelNames: ['code', 'method'],
})

const discardCounter = new Counter({
    name: 'push_subscription_discarded_total',
    help: 'Device registrations acknowledged but not stored, by reason.',
    labelNames: ['reason'],
})

const identityVerificationCounter = new Counter({
    name: 'push_subscription_identity_verification_total',
    help: 'Outcome of push subscription identity token verification.',
    labelNames: ['mode', 'operation', 'outcome'],
})

const requestDuration = new Histogram({
    name: 'push_subscription_request_duration_seconds',
    help: 'Time to answer a device registration request, by method and status.',
    labelNames: ['method', 'status'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

const PATHS = new Set(['/api/push_subscriptions/', '/api/push_subscriptions'])

const DISCARD_LOG_WINDOW_MS = 60_000
let discardLogWindow = 0
let discardedTeamsThisWindow = new Set<number>()

/** Handles `/api/push_subscriptions/` on a plain node http server.
 *
 * Deliberately not built on the plugin server's `ultimate-express`: that framework discards the
 * request body on DELETE, and DELETE with a JSON body is how every released SDK unregisters a
 * device. Verified against ultimate-express 2.0.9 — content-length arrives, the stream never emits,
 * and POST, PUT and PATCH are all unaffected, so it is specific to the verb this endpoint needs.
 */
export function createPushSubscriptionsHandler(service: PushSubscriptionsService) {
    return async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
        const rawUrl = req.url ?? '/'
        const queryStart = rawUrl.indexOf('?')
        // Matched on the raw path, so dot segments and other spellings that URL parsing would
        // normalize onto this path are not served.
        const path = queryStart === -1 ? rawUrl : rawUrl.slice(0, queryStart)
        if (!PATHS.has(path)) {
            res.writeHead(404).end()
            return
        }
        let query: URLSearchParams
        try {
            query = new URLSearchParams(queryStart === -1 ? '' : rawUrl.slice(queryStart + 1))
        } catch {
            query = new URLSearchParams()
        }

        applyCors(req, res)

        if (req.method === 'OPTIONS') {
            // Django answers the preflight with an empty HttpResponse, which carries its default
            // content type. Matching it keeps the preflight byte-identical to today's.
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end('')
            return
        }

        const startedAt = process.hrtime.bigint()
        const body = await readBody(req)
        const result = await service.handle({
            method: req.method ?? 'GET',
            body,
            contentType: header(req, 'content-type'),
            contentEncoding: header(req, 'content-encoding'),
            query,
        })

        const methodLabel = req.method === 'POST' || req.method === 'DELETE' ? req.method : 'other'

        if (result.rejection) {
            rejectionCounter.inc({ code: result.rejection.code, method: methodLabel })
            const sdk = parseUserAgentSdk(header(req, 'user-agent'))
            logger.warn('push_subscription_rejected', {
                code: result.rejection.code,
                status_code: result.status,
                method: req.method,
                team_id: result.rejection.teamId ?? null,
                // Client-supplied, so bounded to keep a hostile value from bloating the log line.
                app_id: typeof result.rejection.appId === 'string' ? result.rejection.appId.slice(0, 128) : null,
                detail: result.rejection.detail ?? null,
                sdk_name: sdk.name,
                sdk_version: sdk.version,
                api_key_fingerprint: result.rejection.apiKeyFingerprint ?? null,
                // Django attaches the traceback for the paths that swallow an exception, so a 500 is
                // diagnosable from this one event rather than only from the counter.
                error: result.rejection.error ? String(result.rejection.error) : null,
            })
        }

        if (result.identityVerification) {
            identityVerificationCounter.inc(result.identityVerification)
        }

        if (result.discarded) {
            discardCounter.inc({ reason: result.discarded.reason })
            if (isFirstDiscardInWindow(result.discarded.teamId)) {
                logger.info('push_subscription_discarded', {
                    reason: result.discarded.reason,
                    team_id: result.discarded.teamId,
                    app_id: result.discarded.appId,
                })
            }
        }

        requestDuration.observe(
            { method: methodLabel, status: String(result.status) },
            Number(process.hrtime.bigint() - startedAt) / 1e9
        )

        res.writeHead(result.status, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(result.body))
    }
}

function header(req: IncomingMessage, name: string): string | undefined {
    const value = req.headers[name]
    return Array.isArray(value) ? value[0] : value
}

/** Reads one byte past the limit, which is what lets the service answer 413 without holding a
 * larger body in memory. */
function readBody(req: IncomingMessage): Promise<Buffer> {
    return new Promise((resolve) => {
        const chunks: Buffer[] = []
        let size = 0
        let settled = false
        const finish = (): void => {
            if (settled) {
                return
            }
            settled = true
            resolve(Buffer.concat(chunks).subarray(0, MAX_BODY_BYTES + 1))
        }
        req.on('data', (chunk: Buffer) => {
            if (size <= MAX_BODY_BYTES) {
                chunks.push(chunk)
                size += chunk.length
            }
        })
        req.on('end', finish)
        req.on('error', finish)
        // A client that disconnects mid-body emits neither, leaking the handler without this.
        req.on('aborted', finish)
        req.on('close', finish)
    })
}

function applyCors(req: IncomingMessage, res: ServerResponse): void {
    if (!header(req, 'origin')) {
        return
    }
    // A wildcard, as Django answers, and no credentials: nothing here reads a cookie, and a
    // reflected origin with credentials would let any site make credentialed calls.
    res.setHeader('Access-Control-Allow-Origin', '*')
    // Django advertises only GET, POST and OPTIONS here while accepting DELETE, so a browser
    // preflight for the unregister call is refused. Native SDKs never preflight, which is why that
    // has gone unnoticed; this deliberately advertises the verb the endpoint actually serves.
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
    res.setHeader('Access-Control-Allow-Headers', 'X-Requested-With,Content-Type')
    res.setHeader('Vary', 'Origin')
}

function isFirstDiscardInWindow(teamId: number): boolean {
    const window = Math.floor(Date.now() / DISCARD_LOG_WINDOW_MS)
    // Replaced rather than added to, so the set holds one window instead of every team seen.
    if (window !== discardLogWindow) {
        discardLogWindow = window
        discardedTeamsThisWindow = new Set()
    }
    if (discardedTeamsThisWindow.has(teamId)) {
        return false
    }
    discardedTeamsThisWindow.add(teamId)
    return true
}

function parseUserAgentSdk(userAgent?: string): { name: string | null; version: string | null } {
    // PostHog SDKs identify as "posthog-<name>/<version>". Each part is bounded, others ignored.
    if (!userAgent || !userAgent.startsWith('posthog-')) {
        return { name: null, version: null }
    }
    const separator = userAgent.indexOf('/')
    if (separator === -1) {
        return { name: null, version: null }
    }
    const version = userAgent.slice(separator + 1).split(/\s/)[0]
    if (!version) {
        return { name: null, version: null }
    }
    return { name: userAgent.slice(0, separator).slice(0, 64), version: version.slice(0, 32) }
}
