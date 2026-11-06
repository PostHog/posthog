import { footerUrl } from '../footer-url'

describe('footerUrl', () => {
    it.each([
        ['https://app.example.com/a/b?utm_source=x&state=abc', 'https://app.example.com/a/b'],
        ['https://app.example.com/a?q=1#panel=access', 'https://app.example.com/a#panel=access'],
        ['https://app.example.com/a#x?not=query', 'https://app.example.com/a#x?not=query'],
        ['https://app.example.com/a', 'https://app.example.com/a'],
        ['not a url?q=1#h', 'not a url#h'],
    ])('drops the query string from %s', (href, expected) => {
        expect(footerUrl(href)).toBe(expected)
    })
})
