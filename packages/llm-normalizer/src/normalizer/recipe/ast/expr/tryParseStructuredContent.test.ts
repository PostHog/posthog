import { Scope } from '../../scope'
import { LiteralExpr } from './literal'
import { TryParseStructuredContentExpr } from './tryParseStructuredContent'

describe('TryParseStructuredContentExpr', () => {
    const scope = Scope.forNode({}, 'user')
    const parse = (value: unknown): unknown => new TryParseStructuredContentExpr(new LiteralExpr(value)).eval(scope)

    it('parses a JSON array of structured-content blocks into objects', () => {
        const blocks = [
            { type: 'text', text: 'hello' },
            { type: 'image_url', image_url: { url: 'x' } },
        ]
        expect(parse(JSON.stringify(blocks))).toEqual(blocks)
    })

    it('leaves a plain (non-array) string untouched', () => {
        expect(parse('just text')).toBe('just text')
    })

    it('returns non-string input unchanged', () => {
        const value = [{ type: 'text', text: 'hi' }]
        expect(parse(value)).toBe(value)
    })

    it('returns the raw string when the JSON is invalid', () => {
        expect(parse('[not valid json')).toBe('[not valid json')
    })
})
