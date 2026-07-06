#!/usr/bin/env tsx
/**
 * ai-gateway integration smoke test.
 *
 * Two modes — pick one as the first positional arg:
 *
 *   probe (default) — resolves a team's `phc_` from posthog_team and sends a
 *     real chat completion to the configured gateway URL, classifying the
 *     response the same way the runner would. Reports PASS/FAIL per step.
 *
 *   echo — runs a tiny HTTP server that mimics the gateway and logs every
 *     inbound header + body. Use it when you want to verify the runner's
 *     outbound wire shape without booting a real gateway. Configurable
 *     response status lets you trigger 402 / 429 / 5xx paths locally.
 *
 * Env vars:
 *   probe mode:
 *     POSTHOG_DB_URL              required — main PostHog DB (reads posthog_team.api_token)
 *     POSTHOG_AI_GATEWAY_URL     default http://localhost:8080/v1
 *     TEAM_ID                     default 1
 *     PROBE_MODEL                 default openai/gpt-4o-mini
 *     PROBE_TIMEOUT_MS            default 15000
 *   echo mode:
 *     ECHO_PORT                   default 8765
 *     ECHO_STATUS                 default 200 — 200 streams a stub SSE body,
 *                                 4xx / 5xx returns the gateway's JSON envelope
 *                                 shape so the runner's classifier fires
 *
 * Examples:
 *   pnpm tsx bin/gateway-smoke.ts probe
 *   POSTHOG_AI_GATEWAY_URL=http://localhost:8765/v1 pnpm tsx bin/gateway-smoke.ts probe
 *   ECHO_STATUS=402 pnpm tsx bin/gateway-smoke.ts echo
 */

import { randomUUID } from 'node:crypto'
import { createServer } from 'node:http'
import pg from 'pg'

import { PgTeamApiKeyResolver, TeamApiKeyNotFoundError } from '@posthog/agent-shared'

const { Pool } = pg

const STEP_FAIL = '✗'

interface ProbeOpts {
    posthogDbUrl: string
    gatewayUrl: string
    teamId: number
    model: string
    timeoutMs: number
}

async function probeMode(): Promise<number> {
    const opts: ProbeOpts = {
        posthogDbUrl: requireEnv('POSTHOG_DB_URL'),
        gatewayUrl: process.env.POSTHOG_AI_GATEWAY_URL ?? 'http://localhost:8080/v1',
        teamId: Number(process.env.TEAM_ID ?? '1'),
        model: process.env.PROBE_MODEL ?? 'openai/gpt-4o-mini',
        timeoutMs: Number(process.env.PROBE_TIMEOUT_MS ?? '15000'),
    }

    // Step 1: resolve the team's phc_.
    let phc: string
    const pool = new Pool({ connectionString: opts.posthogDbUrl })
    try {
        const resolver = new PgTeamApiKeyResolver(pool)
        phc = await resolver.resolve(opts.teamId)
    } catch (err) {
        if (err instanceof TeamApiKeyNotFoundError) {
            console.error(`${STEP_FAIL} step 1: ${err.message}`)
            console.error('   → check posthog_team.api_token for this team_id')
        } else {
            console.error(`${STEP_FAIL} step 1: failed to read posthog_team (${(err as Error).message})`)
        }
        await pool.end()
        return 1
    } finally {
        // pool stays open for cleanup at the very end; close after we're done.
    }

    // Step 2: build the same request shape the runner sends.
    const sessionId = `smoke_${randomUUID()}`
    const headers: Record<string, string> = {
        Authorization: `Bearer ${phc}`,
        'Content-Type': 'application/json',
        'X-PostHog-Distinct-Id': `agent:smoke-${opts.teamId}`,
        'X-PostHog-Trace-Id': sessionId,
        'Idempotency-Key': `agent:${sessionId}:1`,
    }
    // Send the canonical provider-prefixed id ("openai/gpt-4o"). The gateway
    // router admits on this form; the dispatcher's MutateBody hook strips
    // the prefix before forwarding so the upstream provider sees the bare
    // id it expects.
    const body = {
        model: opts.model,
        messages: [{ role: 'user', content: 'reply with the single word OK' }],
        max_tokens: 16,
        stream: true,
    }

    // Step 3: actually call the gateway.

    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(), opts.timeoutMs)
    let res: Response
    try {
        res = await fetch(`${opts.gatewayUrl.replace(/\/$/, '')}/chat/completions`, {
            method: 'POST',
            headers,
            body: JSON.stringify(body),
            signal: ac.signal,
        })
    } catch (err) {
        clearTimeout(timer)
        console.error(`${STEP_FAIL} step 3: network error — ${(err as Error).message}`)
        console.error('   → is the gateway running at', opts.gatewayUrl, '?')
        await pool.end()
        return 1
    }
    clearTimeout(timer)

    const requestId = res.headers.get('x-request-id') ?? res.headers.get('x-posthog-request-id')
    if (requestId) {
    }

    // Step 4: classify the response the same way the runner does.

    if (res.status === 200) {
        // Drain the SSE stream so the gateway settles cleanly.
        await res.text()
        await pool.end()
        return 0
    }

    // Non-2xx: try to read the envelope body for context.
    const bodyText = await res.text().catch(() => '')

    switch (res.status) {
        case 401:
            break
        case 402:
            break
        case 429:
            break
        case 502:
        case 503:
        case 504:
            break
        default:
    }
    if (bodyText) {
    }

    await pool.end()
    // 402 / 429 / 5xx are "integration works, environment isn't ready" — exit 0
    // so CI can treat them as a successful smoke. Only 401 / 400 / 5xx-unknown
    // mean the integration itself is broken.
    return res.status === 401 || res.status >= 500 ? 1 : 0
}

function echoMode(): void {
    const port = Number(process.env.ECHO_PORT ?? '8765')
    const status = Number(process.env.ECHO_STATUS ?? '200')

    createServer((req, res) => {
        let body = ''
        req.on('data', (c: Buffer) => (body += c.toString()))
        req.on('end', () => {
            if (status === 200) {
                // Mimic a minimal OpenAI streaming chat completion so pi-ai's
                // openai-completions provider can consume it without erroring.
                res.writeHead(200, {
                    'Content-Type': 'text/event-stream',
                    'Cache-Control': 'no-cache',
                })
                const chunkId = `chatcmpl-${randomUUID()}`
                const created = Math.floor(Date.now() / 1000)
                const chunk = (delta: object): string =>
                    `data: ${JSON.stringify({
                        id: chunkId,
                        object: 'chat.completion.chunk',
                        created,
                        model: 'echo-gateway',
                        choices: [{ index: 0, delta, finish_reason: null }],
                    })}\n\n`
                res.write(chunk({ role: 'assistant', content: 'OK' }))
                res.write(
                    `data: ${JSON.stringify({
                        id: chunkId,
                        object: 'chat.completion.chunk',
                        created,
                        model: 'echo-gateway',
                        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
                    })}\n\n`
                )
                res.write('data: [DONE]\n\n')
                res.end()
                return
            }
            // 4xx / 5xx — return the gateway's JSON envelope shape so the
            // runner's classifier fires the same way it would in production.
            const envelope = {
                status,
                code: envelopeCodeFor(status),
                message: envelopeMessageFor(status),
                request_id: `echo_${randomUUID()}`,
            }
            res.writeHead(status, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify(envelope))
        })
    }).listen(port)

    process.on('SIGINT', () => {
        process.exit(0)
    })
}

function envelopeCodeFor(status: number): string {
    switch (status) {
        case 401:
            return 'auth_failed'
        case 402:
            return 'insufficient_credits'
        case 429:
            return 'throttled'
        case 502:
            return 'fallback_exhausted'
        default:
            return 'internal'
    }
}

function envelopeMessageFor(status: number): string {
    switch (status) {
        case 401:
            return 'authentication failed'
        case 402:
            return 'admission rejected'
        case 429:
            return 'rate limit exceeded'
        case 502:
            return 'no upstream available'
        default:
            return 'internal error'
    }
}

function requireEnv(name: string): string {
    const v = process.env[name]
    if (!v) {
        console.error(`missing required env: ${name}`)
        process.exit(2)
    }
    return v
}

async function main(): Promise<void> {
    const mode = process.argv[2] ?? 'probe'
    switch (mode) {
        case 'probe':
            process.exit(await probeMode())
            break
        case 'echo':
            echoMode()
            break
        default:
            console.error(`unknown mode: ${mode}`)
            console.error('usage: gateway-smoke.ts [probe|echo]')
            process.exit(2)
    }
}

void main()
