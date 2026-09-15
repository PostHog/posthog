import { IncomingMessage, ServerResponse } from 'http'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { MAX_BODY_BYTES, PushSubscriptionsService } from './push-subscriptions.service'

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

const DISCARD_LOG_WINDOW_MS = 60_000
let discardLogWindow = 0
let discardedTeamsThisWindow = new Set<number>()

/** Handles `/api/push_subscriptions/` on a plain node http server.
 *
 * Deliberately not built on the plugin server's `ultimate-express`: that framework discards the
 * request body on DELETE, and DELETE with a JSON body is how every released SDK unregisters a
 * device. Keeping this on `node:http` leaves the framework an open choice.
 */
export function createPushSubscriptionsHandler(service: PushSubscriptionsService) {
    return async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
        const url = new URL(req.url ?? '/', 'http://localhost')
        if (url.pathname !== '/api/push_subscriptions/' && url.pathname !== '/api/push_subscriptions') {
            res.writeHead(404).end()
            return
        }

        applyCors(req, res)

        if (req.method === 'OPTIONS') {
            res.writeHead(200).end('')
            return
        }

        const body = await readBody(req)
        const result = await service.handle({ method: req.method ?? 'GET', body })

        if (result.rejection) {
            const method = req.method === 'POST' || req.method === 'DELETE' ? req.method : 'other'
            rejectionCounter.inc({ code: result.rejection.code, method })
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
            })
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

        res.writeHead(result.status, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(result.body))
    }
}

function header(req: IncomingMessage, name: string): string | undefined {
    const value = req.headers[name]
    return Array.isArray(value) ? value[0] : value
}

/** Reads at most one byte more than the endpoint accepts.
 *
 * That byte is what separates the two answers: the service reads the length, so a body over the
 * limit stays over it and gets a 413, while nothing larger is ever held in memory.
 */
function readBody(req: IncomingMessage): Promise<Buffer> {
    return new Promise((resolve) => {
        const chunks: Buffer[] = []
        let size = 0
        const finish = (): void => resolve(Buffer.concat(chunks).subarray(0, MAX_BODY_BYTES + 1))
        req.on('data', (chunk: Buffer) => {
            if (size <= MAX_BODY_BYTES) {
                chunks.push(chunk)
                size += chunk.length
            }
        })
        req.on('end', finish)
        req.on('error', finish)
    })
}

function applyCors(req: IncomingMessage, res: ServerResponse): void {
    const origin = header(req, 'origin')
    if (!origin) {
        return
    }
    let allowed = '*'
    try {
        const parsed = new URL(origin)
        allowed = `${parsed.protocol}//${parsed.host}`
    } catch {
        allowed = '*'
    }
    res.setHeader('Access-Control-Allow-Origin', allowed)
    res.setHeader('Access-Control-Allow-Credentials', 'true')
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    res.setHeader('Access-Control-Allow-Headers', 'X-Requested-With,Content-Type')
    res.setHeader('Vary', 'Origin')
}

function isFirstDiscardInWindow(teamId: number): boolean {
    const window = Math.floor(Date.now() / DISCARD_LOG_WINDOW_MS)
    // Replaced rather than added to, so the set holds one window of teams instead of every team the
    // process has ever seen.
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
    // PostHog SDKs identify as "posthog-<name>/<version>", so a rejection can be attributed to the
    // SDK from this log alone. Each part is bounded and any other user agent is ignored.
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
