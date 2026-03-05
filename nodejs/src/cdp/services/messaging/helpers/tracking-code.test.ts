import { generateEmailTrackingCode, parseEmailTrackingCode } from './tracking-code'

describe('tracking-code', () => {
    it.each([
        {
            desc: 'without distinct_id',
            input: { functionId: 'fn-1', id: 'inv-1' },
            distinctId: undefined,
            expected: { functionId: 'fn-1', invocationId: 'inv-1', distinctId: undefined },
        },
        {
            desc: 'with distinct_id',
            input: { functionId: 'fn-1', id: 'inv-1' },
            distinctId: 'user@example.com',
            expected: { functionId: 'fn-1', invocationId: 'inv-1', distinctId: 'user@example.com' },
        },
        {
            desc: 'with UUID distinct_id',
            input: { functionId: 'abc-123', id: 'xyz-456' },
            distinctId: '550e8400-e29b-41d4-a716-446655440000',
            expected: {
                functionId: 'abc-123',
                invocationId: 'xyz-456',
                distinctId: '550e8400-e29b-41d4-a716-446655440000',
            },
        },
    ])('round-trips $desc', ({ input, distinctId, expected }) => {
        const code = generateEmailTrackingCode(input, distinctId)
        const parsed = parseEmailTrackingCode(code)
        expect(parsed).toEqual(expected)
    })

    it('returns null for empty string', () => {
        expect(parseEmailTrackingCode('')).toBeNull()
    })

    it('returns null for invalid base64', () => {
        expect(parseEmailTrackingCode('!!!')).toBeNull()
    })

    it('is backwards compatible with old format (no distinct_id)', () => {
        // Old format: just functionId:invocationId
        const oldCode = generateEmailTrackingCode({ functionId: 'fn-old', id: 'inv-old' })
        const parsed = parseEmailTrackingCode(oldCode)
        expect(parsed).toEqual({
            functionId: 'fn-old',
            invocationId: 'inv-old',
            distinctId: undefined,
        })
    })
})
