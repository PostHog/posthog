import { MAX_USER_AGENT_LENGTH, flattenProperties, parseUserAgent } from './transformation-functions'

const CHROME_UA =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

describe('transformation-functions', () => {
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

        it('still parses a user agent at the length bound', () => {
            const padded = CHROME_UA + ' '.repeat(MAX_USER_AGENT_LENGTH - CHROME_UA.length)

            expect(parseUserAgent(padded)?.browser).toBe('chrome')
        })
    })

    describe('flattenProperties', () => {
        it('flattens nested objects and arrays, keeping originals and matching the legacy plugin', () => {
            expect(flattenProperties({ a: { b: { c: 1 } }, w: { arr: [{ z: 2 }] }, x: 'plain' }, '__')).toEqual({
                a: { b: { c: 1 } },
                w: { arr: [{ z: 2 }] },
                x: 'plain',
                a__b__c: 1,
                w__arr__0__z: 2,
            })
        })

        it('emits a nested empty object as a leaf but not an empty array', () => {
            expect(flattenProperties({ a: { b: {} }, list: { items: [] } }, '__')).toEqual({
                a: { b: {} },
                list: { items: [] },
                a__b: {},
            })
        })

        it('flattens within $set under a fresh prefix and skips internal properties', () => {
            const result = flattenProperties(
                { $set: { user: { id: 7 } }, $elements: { keep: 'nested' } },
                '__'
            ) as Record<string, any>

            expect(result.$set.user__id).toBe(7)
            expect(result.$elements__keep).toBeUndefined()
        })

        it('stays linear for a wide payload', () => {
            const wide: Record<string, any> = {}
            for (let i = 0; i < 50_000; i++) {
                wide[`k${i}`] = { nested: i }
            }
            const start = process.hrtime.bigint()
            const result = flattenProperties({ outer: wide }, '__') as Record<string, any>
            const durationMs = Number(process.hrtime.bigint() - start) / 1e6

            expect(result.outer__k49999__nested).toBe(49999)
            expect(durationMs).toBeLessThan(500)
        })

        it('returns the input unchanged when it is not an object', () => {
            expect(flattenProperties('nope', '__')).toBe('nope')
        })
    })
})
