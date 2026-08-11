import { parseUrl } from './PlayerMeta'

describe('parseUrl', () => {
    test.each([
        {
            name: 'valid URL string',
            input: 'https://example.com',
            expected: { urlToUse: 'https://example.com', isValidUrl: true, isWebUrl: true },
        },
        {
            name: 'location object',
            input: { href: 'https://example.com/path' },
            expected: { urlToUse: 'https://example.com/path', isValidUrl: true, isWebUrl: true },
        },
        {
            name: 'http URL string',
            input: 'http://example.com',
            expected: { urlToUse: 'http://example.com', isValidUrl: true, isWebUrl: true },
        },
        {
            name: 'file URL is valid but not a web URL',
            input: 'file:///Users/someone/index.html',
            expected: { urlToUse: 'file:///Users/someone/index.html', isValidUrl: true, isWebUrl: false },
        },
        {
            name: 'empty object',
            input: {},
            expected: { urlToUse: undefined, isValidUrl: false, isWebUrl: false },
        },
        {
            name: 'undefined',
            input: undefined,
            expected: { urlToUse: undefined, isValidUrl: false, isWebUrl: false },
        },
        {
            name: 'null',
            input: null,
            expected: { urlToUse: undefined, isValidUrl: false, isWebUrl: false },
        },
        {
            name: 'empty string',
            input: '',
            expected: { urlToUse: undefined, isValidUrl: false, isWebUrl: false },
        },
        {
            name: 'whitespace string',
            input: '   ',
            expected: { urlToUse: undefined, isValidUrl: false, isWebUrl: false },
        },
        {
            name: 'invalid URL',
            input: 'not-a-url',
            expected: { urlToUse: 'not-a-url', isValidUrl: false, isWebUrl: false },
        },
        {
            name: 'URL with path and query',
            input: 'https://example.com/path?query=value',
            expected: { urlToUse: 'https://example.com/path?query=value', isValidUrl: true, isWebUrl: true },
        },
        {
            name: 'location object with invalid URL',
            input: { href: 'not-a-url' },
            expected: { urlToUse: 'not-a-url', isValidUrl: false, isWebUrl: false },
        },
    ])('handles $name', ({ input, expected }) => {
        expect(parseUrl(input)).toEqual(expected)
    })
})
