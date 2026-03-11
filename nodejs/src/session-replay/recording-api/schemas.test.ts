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
        const result = GetBlockQuerySchema.safeParse({ key: 'some/key', start_byte: '0', end_byte: '100' })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data.key).toBe('some/key')
            expect(result.data.start_byte).toBe(0)
            expect(result.data.end_byte).toBe(100)
        }
    })

    it('accepts start equal to end', () => {
        const result = GetBlockQuerySchema.safeParse({ key: 'some/key', start_byte: '50', end_byte: '50' })

        expect(result.success).toBe(true)
    })

    it.each([
        { query: { start_byte: '0', end_byte: '100' }, desc: 'missing key' },
        { query: { key: 'k', end_byte: '100' }, desc: 'missing start_byte' },
        { query: { key: 'k', start_byte: '0' }, desc: 'missing end_byte' },
    ])('rejects $desc', ({ query }) => {
        const result = GetBlockQuerySchema.safeParse(query)

        expect(result.success).toBe(false)
    })

    it.each([
        { query: { key: 'k', start_byte: '-1', end_byte: '100' }, desc: 'negative start_byte' },
        { query: { key: 'k', start_byte: 'abc', end_byte: '100' }, desc: 'non-numeric start_byte' },
        { query: { key: 'k', start_byte: '0', end_byte: 'abc' }, desc: 'non-numeric end_byte' },
        { query: { key: 'k', start_byte: '1.5', end_byte: '100' }, desc: 'float start_byte' },
        { query: { key: '', start_byte: '0', end_byte: '100' }, desc: 'empty key' },
    ])('rejects $desc', ({ query }) => {
        const result = GetBlockQuerySchema.safeParse(query)

        expect(result.success).toBe(false)
    })

    it('rejects start_byte greater than end_byte', () => {
        const result = GetBlockQuerySchema.safeParse({ key: 'k', start_byte: '100', end_byte: '50' })

        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.error.issues[0].message).toBe('start_byte must be less than or equal to end_byte')
        }
    })
})
