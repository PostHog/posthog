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
        // JSON.stringify cannot produce these, so the record is written by hand. They parse to
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
        // politeness_key strips the trailing dot, so a record written before the canonicaliser did
        // the same carries a dotted host against a bare key. Comparing them as plain strings drops
        // every such URL as foreign, and those records are already in the topic.
        const value = Buffer.from(
            `{"v":1,"pseudoTeam":"${TEAM}","capturedAtMs":1700000000000,` +
                `"urls":[{"ref":"imageurl:${TEAM}:${HASH}","url":"https://${host}/a.png","host":"${host}"}]}`
        )

        const parsed = parseCollectedUrlsRecord(value, key)

        expect(parsed.ok && parsed.candidates).toHaveLength(1)
    })

    it('accepts an ordinary timestamp', () => {
        const parsed = parseCollectedUrlsRecord(body('"capturedAtMs":1700000000000'), 'example.com')

        expect(parsed.ok).toBe(true)
    })
})
