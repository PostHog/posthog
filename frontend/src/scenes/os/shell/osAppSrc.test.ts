import { osAppSrc } from './osAppSrc'

const ORIGIN = 'https://app.example.com'

describe('osAppSrc', () => {
    test.each([
        ['an app path', '/replay?filter=1#top', '/replay?filter=1#top'],
        ['a full URL on this origin', `${ORIGIN}/insights`, '/insights'],
        ['another site', 'https://evil.example/x?y=1', null],
        ['a protocol-relative URL', '//evil.example/steal', null],
        ['a javascript URL', 'javascript:alert(1)', null],
        ['a URL that does not parse', 'http://', null],
    ])('%s', (_description, href, expected) => {
        expect(osAppSrc(href, ORIGIN)).toBe(expected)
    })
})
