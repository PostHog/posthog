import { classifyGatewayError } from './gateway-error'

describe('classifyGatewayError', () => {
    it('returns null for an undefined message', () => {
        expect(classifyGatewayError(undefined)).toBeNull()
    })

    it('returns null for a message without a status prefix', () => {
        expect(classifyGatewayError('Connection error.')).toBeNull()
        expect(classifyGatewayError('Stream ended without finish_reason')).toBeNull()
    })

    it.each([
        ['402 admission rejected', { status: 402, kind: 'insufficient_credits' as const }],
        [
            // Gateway sometimes returns the JSON envelope inline; OpenAI SDK
            // formats as `${status} ${JSON.stringify(error)}`.
            '402 {"status":402,"code":"insufficient_credits","message":"admission rejected"}',
            { status: 402, kind: 'insufficient_credits' as const },
        ],
        ['429 rate limited', { status: 429, kind: 'throttled' as const }],
        ['401 authentication failed', { status: 401, kind: 'auth_failed' as const }],
        ['400 invalid request body', { status: 400, kind: 'bad_request' as const }],
        ['502 no upstream available', { status: 502, kind: 'upstream' as const }],
        ['503 upstream temporarily unavailable', { status: 503, kind: 'upstream' as const }],
        ['504 upstream timeout', { status: 504, kind: 'upstream' as const }],
        ['418 teapot', { status: 418, kind: 'other' as const }],
    ])('classifies %j', (msg, expected) => {
        expect(classifyGatewayError(msg)).toEqual(expected)
    })
})
