import { parseUrl } from './PlayerMeta'

describe('parseUrl', () => {
    test.each([
        {
            name: 'valid URL string',
            input: 'https://example.com',
            expected: { urlToUse: 'https://example.com', isValidUrl: true },
        },
        {
            name: 'location object',
            input: { href: 'https://example.com/path' },
            expected: { urlToUse: 'https://example.com/path', isValidUrl: true },
        },
        {
            name: 'empty object',
            input: {},
            expected: { urlToUse: undefined, isValidUrl: false },
        },
        {
            name: 'undefined',
            input: undefined,
            expected: { urlToUse: undefined, isValidUrl: false },
        },
        {
            name: 'null',
            input: null,
            expected: { urlToUse: undefined, isValidUrl: false },
        },
        {
            name: 'empty string',
            input: '',
            expected: { urlToUse: undefined, isValidUrl: false },
        },
        {
            name: 'whitespace string',
            input: '   ',
            expected: { urlToUse: undefined, isValidUrl: false },
        },
        {
            name: 'invalid URL',
            input: 'not-a-url',
            expected: { urlToUse: 'not-a-url', isValidUrl: false },
        },
        {
            name: 'URL with path and query',
            input: 'https://example.com/path?query=value',
            expected: { urlToUse: 'https://example.com/path?query=value', isValidUrl: true },
        },
        {
            name: 'location object with invalid URL',
            input: { href: 'not-a-url' },
            expected: { urlToUse: 'not-a-url', isValidUrl: false },
        },
    ])('handles $name', ({ input, expected }) => {
        expect(parseUrl(input)).toEqual(expected)
    })
})
