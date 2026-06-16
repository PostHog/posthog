import { createHmac } from 'crypto'
import type { Request } from 'express'
import { describe, expect, it } from 'vitest'

import { verifySlackSignature } from './slack-signature'

const SECRET = 'signing-secret'

function signedReq(opts: { ts: string; body?: string }): Request {
    const body = opts.body ?? '{}'
    const base = `v0:${opts.ts}:${body}`
    const mac = createHmac('sha256', SECRET).update(base).digest('hex')
    return {
        headers: { 'x-slack-request-timestamp': opts.ts, 'x-slack-signature': `v0=${mac}` },
        body: JSON.parse(body),
        rawBody: body,
    } as unknown as Request
}

describe('verifySlackSignature', () => {
    it('accepts a fresh, correctly-signed request', () => {
        const ts = String(Math.floor(Date.now() / 1000))
        expect(verifySlackSignature(signedReq({ ts }), SECRET)).toBe(true)
    })

    it('rejects a stale timestamp', () => {
        const ts = String(Math.floor(Date.now() / 1000) - 600)
        expect(verifySlackSignature(signedReq({ ts }), SECRET)).toBe(false)
    })

    it.each([['not-a-number'], ['']])(
        'rejects a non-numeric timestamp %j (NaN must not skip the staleness check)',
        (ts) => {
            // A correctly-signed request whose timestamp is non-numeric: parseInt
            // yields NaN, and `Math.abs(now - NaN) > 300` is false, which previously
            // skipped the staleness window entirely.
            expect(verifySlackSignature(signedReq({ ts }), SECRET)).toBe(false)
        }
    )

    it('rejects when headers are missing', () => {
        expect(verifySlackSignature({ headers: {}, body: {} } as unknown as Request, SECRET)).toBe(false)
    })
})
