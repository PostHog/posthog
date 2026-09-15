import { parseLogBodyForIngestion } from './log-body-parse'

describe('log-body-parse', () => {
    it('returns empty for null body', () => {
        expect(parseLogBodyForIngestion(null)).toEqual({ kind: 'empty' })
    })

    it('classifies JSON object', () => {
        const body = JSON.stringify({ a: 1 })
        const r = parseLogBodyForIngestion(body)
        expect(r).toEqual({ kind: 'json_object_or_array', value: { a: 1 } })
    })

    it('classifies JSON array', () => {
        const r = parseLogBodyForIngestion('[1,2]')
        expect(r).toEqual({ kind: 'json_object_or_array', value: [1, 2] })
    })

    it('classifies JSON string primitive', () => {
        const r = parseLogBodyForIngestion('"hi"')
        expect(r).toEqual({ kind: 'json_string', value: 'hi' })
    })

    it('classifies JSON number primitive', () => {
        const r = parseLogBodyForIngestion('42')
        expect(r).toEqual({ kind: 'json_primitive', parsed: 42 })
    })

    it('returns invalid_json on parse failure', () => {
        const raw = 'not json {'
        expect(parseLogBodyForIngestion(raw)).toEqual({ kind: 'invalid_json', raw })
    })
})
