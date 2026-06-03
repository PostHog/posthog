import { openInAppTargetOrigin, parseUrl } from './PlayerMeta'

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

describe('openInAppTargetOrigin', () => {
    test.each([
        { name: 'no param', input: '', expected: null },
        { name: 'unrelated params', input: '?foo=bar', expected: null },
        { name: 'https origin', input: '?open_in_app=https://app.insforge.com', expected: 'https://app.insforge.com' },
        {
            name: 'strips path to origin',
            input: '?open_in_app=https://app.insforge.com/some/path',
            expected: 'https://app.insforge.com',
        },
        { name: 'http origin', input: '?open_in_app=http://localhost:8000', expected: 'http://localhost:8000' },
        { name: 'non-http scheme rejected', input: '?open_in_app=javascript:alert(1)', expected: null },
        { name: 'bare truthy value rejected', input: '?open_in_app=1', expected: null },
        { name: 'garbage value rejected', input: '?open_in_app=not-a-url', expected: null },
    ])('handles $name', ({ input, expected }) => {
        expect(openInAppTargetOrigin(input)).toEqual(expected)
    })
})
