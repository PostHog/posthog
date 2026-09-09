import { MAX_USER_AGENT_LENGTH, parseUserAgent } from './transformation-functions'

const CHROME_UA =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

describe('parseUserAgent', () => {
    it('parses a real user agent', () => {
        expect(parseUserAgent(CHROME_UA)).toEqual({
            browser: 'chrome',
            browserVersion: '120.0.0',
            os: 'Mac OS',
            browserType: 'browser',
            device: '',
            deviceType: 'Desktop',
        })
    })

    it.each([
        ['a non-string', 42],
        ['an empty string', ''],
    ])('returns null for %s', (_label, value) => {
        expect(parseUserAgent(value)).toBeNull()
    })

    it('returns null past the length bound without parsing', () => {
        // Repeated `Chrom` tokens are the adversarial shape: detect-browser backtracks
        // quadratically on them, so an unbounded value would stall the whole worker.
        const hostile = 'Chrom'.repeat((100 * 1024) / 5)

        const start = process.hrtime.bigint()
        expect(parseUserAgent(hostile)).toBeNull()
        const durationMs = Number(process.hrtime.bigint() - start) / 1e6

        // Generous next to the ~1800ms an unbounded parse of this value costs, but tight enough
        // to fail if the value ever reaches detect-browser again.
        expect(durationMs).toBeLessThan(100)
    })

    it('parses a hostile value at the accepted maximum length quickly', () => {
        // The adversarial `Chrom` pattern at exactly the accepted maximum still reaches
        // detect-browser, so the bound must be low enough that even this stays cheap.
        const hostileAtMax = 'Chrom'.repeat(Math.floor(MAX_USER_AGENT_LENGTH / 5))

        const start = process.hrtime.bigint()
        parseUserAgent(hostileAtMax)
        const durationMs = Number(process.hrtime.bigint() - start) / 1e6

        expect(durationMs).toBeLessThan(10)
    })

    it('still parses a user agent at the length bound', () => {
        const padded = CHROME_UA + ' '.repeat(MAX_USER_AGENT_LENGTH - CHROME_UA.length)

        expect(parseUserAgent(padded)?.browser).toBe('chrome')
    })
})
