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

    // A body that cannot start a JSON document never reaches `parseJSON`. Each row here starts a
    // valid document, so a narrower skip would misreport it as `invalid_json`.
    it.each([
        ['object', '{"a":1}', { kind: 'json_object_or_array', value: { a: 1 } }],
        ['object behind leading whitespace', ' \r\n\t{"a":1}', { kind: 'json_object_or_array', value: { a: 1 } }],
        ['array behind leading whitespace', '\n[1,2]', { kind: 'json_object_or_array', value: [1, 2] }],
        ['string', '"hi"', { kind: 'json_string', value: 'hi' }],
        ['negative number', '-7', { kind: 'json_primitive', parsed: -7 }],
        ['true', 'true', { kind: 'json_primitive', parsed: true }],
        ['false', 'false', { kind: 'json_primitive', parsed: false }],
        ['null', 'null', { kind: 'json_primitive', parsed: null }],
    ])('decodes a body that starts with %s', (_name, body, expected) => {
        expect(parseLogBodyForIngestion(body)).toEqual(expected)
    })

    // The skip is a pre-filter, not a verdict. These bodies pass it and still fail the parse.
    it.each([
        ['null pointer at line 4'],
        ['true and false both reported'],
        ['-- person processing disabled'],
        ['404 not found'],
        ['   '],
        [''],
    ])('returns invalid_json for %p', (raw) => {
        expect(parseLogBodyForIngestion(raw)).toEqual({ kind: 'invalid_json', raw })
    })
})
