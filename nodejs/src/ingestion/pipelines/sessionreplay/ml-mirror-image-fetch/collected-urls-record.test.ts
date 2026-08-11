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

    it('accepts an ordinary timestamp', () => {
        const parsed = parseCollectedUrlsRecord(body('"capturedAtMs":1700000000000'), 'example.com')

        expect(parsed.ok).toBe(true)
    })
})
