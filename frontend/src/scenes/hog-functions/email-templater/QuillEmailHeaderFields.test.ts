import { readableFieldError } from './QuillEmailHeaderFields'

describe('readableFieldError', () => {
    it.each([
        [
            'Liquid template error: tag "endif" not found, line:1, col:29',
            'Liquid syntax problem at character 29: tag "endif" not found',
        ],
        ['Liquid template error: unexpected token', 'Liquid syntax problem: unexpected token'],
        ['Add a subject line', 'Add a subject line'],
        [undefined, undefined],
    ])('%s', (error, expected) => {
        expect(readableFieldError(error)).toBe(expected)
    })
})
