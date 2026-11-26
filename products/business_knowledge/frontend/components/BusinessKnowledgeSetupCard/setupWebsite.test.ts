import { normalizeWebsiteUrl, pickWebsiteFromHosts, websiteSourceName } from './setupWebsite'

describe('setupWebsite', () => {
    it.each([
        ['the most visited public host', ['hedgebox.net', 'docs.hedgebox.net'], 'https://hedgebox.net'],
        [
            'a host behind local development traffic',
            ['localhost:8010', '127.0.0.1:3000', 'hedgebox.net'],
            'https://hedgebox.net',
        ],
        ['a host with a port and capitals', ['Hedgebox.net:443'], 'https://hedgebox.net'],
        ['nothing when every host is private', ['localhost', 'app.local', 'staging.internal', '10.0.0.4'], null],
        ['nothing when there are no pageviews', [], null],
    ])('suggests %s', (_, hosts, expected) => {
        expect(pickWebsiteFromHosts(hosts)).toBe(expected)
    })

    it.each([
        ['hedgebox.net', 'https://hedgebox.net'],
        ['  hedgebox.net/docs ', 'https://hedgebox.net/docs'],
        ['http://hedgebox.net', 'http://hedgebox.net'],
        ['', ''],
    ])('normalizes %j to %j', (raw, expected) => {
        expect(normalizeWebsiteUrl(raw)).toBe(expected)
    })

    it.each([
        ['https://www.hedgebox.net/docs', 'hedgebox.net'],
        ['https://docs.hedgebox.net', 'docs.hedgebox.net'],
        ['https://', null],
    ])('names the source for %j', (url, expected) => {
        expect(websiteSourceName(url)).toBe(expected)
    })
})
