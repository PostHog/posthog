import { defaultAllowLists } from './default-dict'
import { scrubConsolePlugin, scrubGenericField, scrubNetworkPlugin } from './value'

describe('anonymize/value', () => {
    const ctx = { allow: defaultAllowLists() }

    describe('scrubGenericField', () => {
        it('recurses objects/arrays, scrubs string leaves, leaves keys and non-strings alone', () => {
            const owner = {
                payload: {
                    a: 'Hello SecretName',
                    b: ['Hello SecretName', 42, true],
                    c: { url: 'https://example.com/user/abc/profile?token=secret' },
                },
            }
            expect(scrubGenericField(ctx, owner, 'payload')).toBe(true)
            expect(owner.payload.a).toBe('Hello **********')
            expect(owner.payload.b[0]).toBe('Hello **********')
            expect(owner.payload.b[1]).toBe(42)
            expect(owner.payload.b[2]).toBe(true)
            // http(s) string leaves are URL-scrubbed (denied query dropped), not text-scrubbed.
            expect(owner.payload.c.url).toBe('https://example.com/user/[redacted]/profile')
        })

        it('scrubs a bare string field in place', () => {
            const owner: Record<string, unknown> = { payload: 'Hello SecretName' }
            expect(scrubGenericField(ctx, owner, 'payload')).toBe(true)
            expect(owner.payload).toBe('Hello **********')
        })

        it('reports no change when nothing is scrubbable', () => {
            const owner = { payload: { count: 1, ok: true } }
            expect(scrubGenericField(ctx, owner, 'payload')).toBe(false)
        })
    })

    describe('scrubNetworkPlugin', () => {
        it('scrubs request header values', () => {
            const owner = {
                payload: { requests: [{ requestHeaders: { Authorization: 'Bearer SecretToken' } }] },
            }
            expect(scrubNetworkPlugin(ctx, owner, 'payload')).toBe(true)
            expect(owner.payload.requests[0].requestHeaders.Authorization).toBe('Bearer ***********')
        })

        it('falls back to a generic scrub when the payload is not an object', () => {
            const owner: Record<string, unknown> = { payload: 'Hello SecretName' }
            expect(scrubNetworkPlugin(ctx, owner, 'payload')).toBe(true)
            expect(owner.payload).toBe('Hello **********')
        })

        it('returns no change when the requests array is missing', () => {
            const owner = { payload: { somethingElse: 1 } }
            expect(scrubNetworkPlugin(ctx, owner, 'payload')).toBe(false)
        })
    })

    describe('scrubConsolePlugin', () => {
        it('falls back to a generic scrub when the payload is not an object', () => {
            const owner: Record<string, unknown> = { payload: 'Hello SecretName' }
            expect(scrubConsolePlugin(ctx, owner, 'payload')).toBe(true)
            expect(owner.payload).toBe('Hello **********')
        })
    })
})
