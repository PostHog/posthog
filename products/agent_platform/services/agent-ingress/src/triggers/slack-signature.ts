/**
 * Slack request signature verification. Pulled into its own module so both
 * the slack trigger handlers and the `slack_signing` route guard (mount.ts)
 * verify identically — the guard is the enforcement point, the trigger reads
 * the already-verified request.
 */

import { createHmac, timingSafeEqual } from 'crypto'
import { Request } from 'express'

export function verifySlackSignature(req: Request, signingSecret: string): boolean {
    const ts = req.headers['x-slack-request-timestamp']
    const sig = req.headers['x-slack-signature']
    if (typeof ts !== 'string' || typeof sig !== 'string') {
        return false
    }
    const now = Math.floor(Date.now() / 1000)
    const tsNum = parseInt(ts, 10)
    // A non-numeric timestamp parses to NaN, and `Math.abs(now - NaN) > 300`
    // is false — which would silently SKIP the staleness window. Reject
    // non-finite timestamps explicitly before the freshness check.
    if (!Number.isFinite(tsNum) || Math.abs(now - tsNum) > 60 * 5) {
        return false
    }
    const raw = ((req as Request & { rawBody?: string }).rawBody ?? JSON.stringify(req.body)) as string
    const base = `v0:${ts}:${raw}`
    const mac = createHmac('sha256', signingSecret).update(base).digest('hex')
    const expected = `v0=${mac}`
    if (sig.length !== expected.length) {
        return false
    }
    return timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
}
