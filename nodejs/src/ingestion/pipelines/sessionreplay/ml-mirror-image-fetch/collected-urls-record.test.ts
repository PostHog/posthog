import { parseCollectedUrlsRecord } from './collected-urls-record'

const TEAM = '0123456789abcdef0123456789abcdef'
const HASH = 'a'.padEnd(22, '0')

function body(fields: string): Buffer {
    return Buffer.from(
        `{"v":1,"pseudoTeam":"${TEAM}",${fields},` +
            `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"https://cdn.example.com/a.png","host":"cdn.example.com"}]}`
    )
}

describe('parseCollectedUrlsRecord', () => {
    it.each([
        ['a magnitude no double can hold', '"capturedAtMs":-1e400'],
        ['a positive one', '"capturedAtMs":1e400'],
    ])('refuses %s rather than passing a non-finite timestamp on', (_name, fields) => {
        // JSON.stringify cannot produce these, so this writes the record by hand. They parse to
        // Infinity, which reaches a histogram as an infinite observation, and prom-client throws
        // there. A throw inside a batch stops the consumer and replays the same record forever.
        const parsed = parseCollectedUrlsRecord(body(fields), 'example.com')

        expect(parsed).toEqual({ ok: false, reason: 'malformed' })
    })

    it.each([
        ['a fully qualified host against a bare key', 'cdn.example.com.', 'example.com'],
        ['a bare host against a fully qualified key', 'cdn.example.com', 'example.com.'],
        ['both fully qualified', 'cdn.example.com.', 'example.com.'],
    ])('keeps %s', (_name, host, key) => {
        // politenessKey strips the trailing dot, so a record written before the canonicalizer did
        // the same carries a dotted host against a bare key. A plain string comparison drops every
        // such URL as foreign, and those records are already in the topic.
        const value = Buffer.from(
            `{"v":1,"pseudoTeam":"${TEAM}","capturedAtMs":1700000000000,` +
                `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"https://${host}/a.png","host":"${host}"}]}`
        )

        const parsed = parseCollectedUrlsRecord(value, key)

        expect(parsed.ok && parsed.candidates).toHaveLength(1)
    })

    it.each([
        ['a key that is a subdomain rather than the operator', 'cdn.example.com', 'cdn.example.com'],
        ['a key belonging to another operator', 'cdn.example.com', 'other.net'],
    ])('drops %s (requirement 3)', (_name, host, key) => {
        // The key scopes the rate budget. One key for each subdomain would give one operator a
        // multiple of the rate we promise it, and the record would be on the wrong partition too.
        const value = Buffer.from(
            `{"v":1,"pseudoTeam":"${TEAM}","capturedAtMs":1700000000000,` +
                `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"https://${host}/a.png","host":"${host}"}]}`
        )

        const parsed = parseCollectedUrlsRecord(value, key)

        expect(parsed.ok && parsed.candidates).toHaveLength(0)
        expect(parsed.ok && parsed.rejected).toEqual([{ reason: 'foreign_domain' }])
    })

    it.each([
        ['plain HTTP', 'http://cdn.example.com/a.png'],
        ['a scheme this lane never fetches', 'ftp://cdn.example.com/a.png'],
    ])('drops %s (requirements 34 and 35)', (_name, url) => {
        // The collector produces HTTPS only. Anything else means a wrong or stale producer, and a
        // fetch would put an image on the wire in clear text.
        const value = Buffer.from(
            `{"v":1,"pseudoTeam":"${TEAM}","capturedAtMs":1700000000000,` +
                `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"${url}","host":"cdn.example.com"}]}`
        )

        const parsed = parseCollectedUrlsRecord(value, 'example.com')

        expect(parsed.ok && parsed.rejected).toEqual([{ reason: 'bad_url' }])
    })

    it.each([
        ['a name that only resolves inside a network', 'wiki.corp'],
        ['a link-local address', '169.254.169.254'],
        ['a loopback address', '127.0.0.1'],
    ])('drops %s (requirement 35)', (_name, host) => {
        // The connect-time address check cannot refuse a name like wiki.corp whose DNS answer is
        // public, so this is the only place that does.
        const value = Buffer.from(
            `{"v":1,"pseudoTeam":"${TEAM}","capturedAtMs":1700000000000,` +
                `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"https://${host}/a.png","host":"${host}"}]}`
        )

        const parsed = parseCollectedUrlsRecord(value, host)

        expect(parsed.ok && parsed.rejected).toEqual([{ reason: 'private_host' }])
    })

    it('keys one domain by one spelling, whatever the record key used', () => {
        // The budget, the metrics, and the republish key all read this. Two spellings of one
        // domain would take two budgets on the same pod, so each would get the full rate.
        const value = Buffer.from(
            `{"v":1,"pseudoTeam":"${TEAM}","capturedAtMs":1700000000000,` +
                `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"https://cdn.example.com/a.png","host":"cdn.example.com"}]}`
        )

        const dotted = parseCollectedUrlsRecord(value, 'example.com.')
        const bare = parseCollectedUrlsRecord(value, 'example.com')

        expect(dotted.ok && dotted.candidates[0].domain).toBe('example.com')
        expect(bare.ok && bare.candidates[0].domain).toBe('example.com')
    })

    it('accepts an ordinary timestamp', () => {
        const parsed = parseCollectedUrlsRecord(body('"capturedAtMs":1700000000000'), 'example.com')

        expect(parsed.ok).toBe(true)
    })
})
