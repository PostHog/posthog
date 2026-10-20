import { isEmailLikeSearch, isUrlLikeSearch } from './valueSearchQuery'

describe('value search queries', () => {
    it.each([
        ['sample', false, false],
        ['email', false, false],
        ['url', false, false],
        ['sample@', true, false],
        ['sample@example.com', true, false],
        ['/overview', false, true],
        ['docs/overview', false, true],
        ['https:', false, true],
        ['HTTPS://', false, true],
        ['www.', false, true],
        ['example.com', true, true],
        ['mail.example.com', true, true],
        ['example.com:8080', false, true],
        ['https://example.com', false, true],
        ['example.com/path', false, true],
        ['  example.com  ', true, true],
        ['a sentence with example.com', false, false],
    ])('recognizes %s as email=%s and URL=%s', (query, emailLike, urlLike) => {
        expect(isEmailLikeSearch(query)).toBe(emailLike)
        expect(isUrlLikeSearch(query)).toBe(urlLike)
    })
})
