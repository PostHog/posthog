import { GetBlockQuerySchema, RecordingParamsSchema } from './schemas'

describe('RecordingParamsSchema', () => {
    it.each([
        ['1', 'session-123'],
        ['999', 'abc-def-ghi'],
        ['42', 'a'],
    ])('accepts valid params: team_id=%s, session_id=%s', (team_id, session_id) => {
        const result = RecordingParamsSchema.safeParse({ team_id, session_id })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data.team_id).toBe(Number(team_id))
            expect(result.data.session_id).toBe(session_id)
        }
    })

    it.each([
        ['0', 'zero'],
        ['-1', 'negative'],
        ['abc', 'non-numeric'],
        ['1.5', 'float'],
        ['', 'empty string'],
    ])('rejects invalid team_id: %s (%s)', (team_id) => {
        const result = RecordingParamsSchema.safeParse({ team_id, session_id: 'session-1' })

        expect(result.success).toBe(false)
    })

    it('rejects empty session_id', () => {
        const result = RecordingParamsSchema.safeParse({ team_id: '1', session_id: '' })

        expect(result.success).toBe(false)
    })
})

describe('GetBlockQuerySchema', () => {
    it('accepts valid query params', () => {
        const result = GetBlockQuerySchema.safeParse({ key: 'some/key', start: '0', end: '100' })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data.key).toBe('some/key')
            expect(result.data.start).toBe(0)
            expect(result.data.end).toBe(100)
        }
    })

    it('accepts start equal to end', () => {
        const result = GetBlockQuerySchema.safeParse({ key: 'some/key', start: '50', end: '50' })

        expect(result.success).toBe(true)
    })

    it.each([
        { query: { start: '0', end: '100' }, desc: 'missing key' },
        { query: { key: 'k', end: '100' }, desc: 'missing start' },
        { query: { key: 'k', start: '0' }, desc: 'missing end' },
    ])('rejects $desc', ({ query }) => {
        const result = GetBlockQuerySchema.safeParse(query)

        expect(result.success).toBe(false)
    })

    it.each([
        { query: { key: 'k', start: '-1', end: '100' }, desc: 'negative start' },
        { query: { key: 'k', start: 'abc', end: '100' }, desc: 'non-numeric start' },
        { query: { key: 'k', start: '0', end: 'abc' }, desc: 'non-numeric end' },
        { query: { key: 'k', start: '1.5', end: '100' }, desc: 'float start' },
        { query: { key: '', start: '0', end: '100' }, desc: 'empty key' },
    ])('rejects $desc', ({ query }) => {
        const result = GetBlockQuerySchema.safeParse(query)

        expect(result.success).toBe(false)
    })

    it('rejects start greater than end', () => {
        const result = GetBlockQuerySchema.safeParse({ key: 'k', start: '100', end: '50' })

        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.error.issues[0].message).toBe('start must be less than or equal to end')
        }
    })
})
