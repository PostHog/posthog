import { parseJsonObject } from './utils'

describe('dataset JSON utils', () => {
    it.each([
        ['an array', '[1, 2]'],
        ['a number', '5'],
        ['null', 'null'],
    ])('rejects %s where a JSON object is required', (_name, value) => {
        expect(() => parseJsonObject(value)).toThrow(TypeError)
    })

    it.each([
        ['a populated object', '{"key": "value"}', { key: 'value' }],
        ['an empty object', '{}', {}],
        ['an empty string', '', {}],
        ['null input', null, {}],
    ])('parses %s', (_name, value, expected) => {
        expect(parseJsonObject(value)).toEqual(expected)
    })
})
