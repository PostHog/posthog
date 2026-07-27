import { isNonFailureStatus } from './non-failure-status-codes'

describe('isNonFailureStatus', () => {
    describe('exact numeric matches', () => {
        it.each([
            [400, [400], true],
            [400, [400, 429], true],
            [429, [400, 429], true],
            [400, [401], false],
            [200, [200], true],
            [500, [500], true],
        ])('status %p in %p => %p', (status, config, expected) => {
            expect(isNonFailureStatus(status, config)).toBe(expected)
        })
    })

    describe('wildcard matches', () => {
        it.each([
            [400, ['4xx'], true],
            [404, ['4xx'], true],
            [499, ['4xx'], true],
            [500, ['4xx'], false],
            [399, ['4xx'], false],
            [500, ['5xx'], true],
            [599, ['5xx'], true],
            [400, ['5xx'], false],
            // Only 4xx and 5xx wildcards are supported — non-failure config is irrelevant outside the error range.
            [100, ['1xx'], false],
            [200, ['2xx'], false],
            [301, ['3xx'], false],
        ])('status %p in %p => %p', (status, config, expected) => {
            expect(isNonFailureStatus(status, config)).toBe(expected)
        })
    })

    describe('mixed wildcards and numbers', () => {
        it('matches a 4xx via wildcard and a specific 500', () => {
            expect(isNonFailureStatus(404, ['4xx', 500])).toBe(true)
            expect(isNonFailureStatus(500, ['4xx', 500])).toBe(true)
            expect(isNonFailureStatus(502, ['4xx', 500])).toBe(false)
        })

        it('matches when only one entry hits', () => {
            expect(isNonFailureStatus(429, [400, '5xx'])).toBe(false)
            expect(isNonFailureStatus(503, [400, '5xx'])).toBe(true)
        })
    })

    describe('empty / missing config', () => {
        it.each([
            [400, null],
            [400, undefined],
            [400, []],
        ])('status %p with config %p returns false', (status, config) => {
            expect(isNonFailureStatus(status, config as any)).toBe(false)
        })
    })

    describe('missing status', () => {
        it('returns false when status is undefined', () => {
            expect(isNonFailureStatus(undefined, ['4xx', 500])).toBe(false)
        })
    })

    describe('invalid entries are silently dropped', () => {
        it.each([
            [400, ['foo', 400], true],
            [400, ['9xx', '4xx'], true],
            [400, [-1, 1000, 400], true],
            [400, ['abc', null, undefined, 400], true],
            [400, ['foo', 'bar'], false],
            [400, [-1, 1000], false],
        ])('status %p with config %p => %p', (status, config, expected) => {
            expect(isNonFailureStatus(status, config as any)).toBe(expected)
        })
    })

    describe('case insensitivity for wildcards', () => {
        it('accepts 4XX as well as 4xx', () => {
            expect(isNonFailureStatus(404, ['4XX'])).toBe(true)
            expect(isNonFailureStatus(404, ['4Xx'])).toBe(true)
        })
    })
})
