import { type PropertyFilterLeaf, compileLeafRegex, matchPropertyFilter } from './property-filter-match'

const filter = (overrides: Partial<PropertyFilterLeaf>): PropertyFilterLeaf => ({
    key: 'k',
    ...overrides,
})

describe('matchPropertyFilter', () => {
    describe('exact / is_not / in / not_in', () => {
        it('exact matches case-insensitively', () => {
            expect(matchPropertyFilter(filter({ operator: 'exact', value: 'prod' }), 'PROD')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'exact', value: 'prod' }), 'staging')).toBe(false)
        })
        it('is_not is the negation of exact', () => {
            expect(matchPropertyFilter(filter({ operator: 'is_not', value: 'prod' }), 'staging')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'is_not', value: 'prod' }), 'prod')).toBe(false)
        })
        it('exact with a list matches when any value matches case-insensitively', () => {
            expect(matchPropertyFilter(filter({ operator: 'exact', value: ['a', 'b'] }), 'A')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'exact', value: ['a', 'b'] }), 'c')).toBe(false)
        })
        it('in is an alias for exact-with-list', () => {
            expect(matchPropertyFilter(filter({ operator: 'in', value: ['error', 'fatal'] }), 'error')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'in', value: ['error', 'fatal'] }), 'warn')).toBe(false)
        })
        it('not_in is the negation of in', () => {
            expect(matchPropertyFilter(filter({ operator: 'not_in', value: ['error', 'fatal'] }), 'warn')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'not_in', value: ['error', 'fatal'] }), 'error')).toBe(false)
        })
        it('truthy values normalise to "true"/"false" strings', () => {
            expect(matchPropertyFilter(filter({ operator: 'exact', value: true }), 'true')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'exact', value: 'True' }), 'true')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'exact', value: false }), 'false')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'exact', value: true }), 'false')).toBe(false)
        })
    })

    describe('icontains / not_icontains', () => {
        it('icontains is case-insensitive substring', () => {
            expect(matchPropertyFilter(filter({ operator: 'icontains', value: 'HEALTH' }), '/healthz')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'icontains', value: 'foo' }), '/healthz')).toBe(false)
        })
        it('not_icontains negates icontains', () => {
            expect(matchPropertyFilter(filter({ operator: 'not_icontains', value: 'foo' }), '/healthz')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'not_icontains', value: 'HEALTH' }), '/healthz')).toBe(false)
        })
    })

    describe('regex / not_regex', () => {
        it('regex matches with dotall + ignorecase semantics (Python parity)', () => {
            expect(matchPropertyFilter(filter({ operator: 'regex', value: '^/api/' }), '/API/v1')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'regex', value: '^/api/' }), '/health')).toBe(false)
            // `.` matches newline thanks to the `s` flag
            expect(matchPropertyFilter(filter({ operator: 'regex', value: 'first.second' }), 'first\nsecond')).toBe(
                true
            )
        })
        it('invalid regex returns false without throwing', () => {
            expect(matchPropertyFilter(filter({ operator: 'regex', value: '[unclosed' }), 'anything')).toBe(false)
        })
        it('not_regex negates regex', () => {
            expect(matchPropertyFilter(filter({ operator: 'not_regex', value: '^/api/' }), '/health')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'not_regex', value: '^/api/' }), '/API/v1')).toBe(false)
        })
    })

    describe('is_set / is_not_set', () => {
        it('is_set matches when override is a non-empty value', () => {
            expect(matchPropertyFilter(filter({ operator: 'is_set' }), 'anything')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'is_set' }), '')).toBe(false)
            expect(matchPropertyFilter(filter({ operator: 'is_set' }), undefined)).toBe(false)
            expect(matchPropertyFilter(filter({ operator: 'is_set' }), null)).toBe(false)
        })
        it('is_not_set matches when override is undefined / null / empty', () => {
            expect(matchPropertyFilter(filter({ operator: 'is_not_set' }), undefined)).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'is_not_set' }), null)).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'is_not_set' }), '')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'is_not_set' }), 'anything')).toBe(false)
        })
    })

    describe('gt / gte / lt / lte', () => {
        it('compares numerically when both sides parse as numbers', () => {
            expect(matchPropertyFilter(filter({ operator: 'gt', value: '100' }), '200')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'gt', value: '100' }), '50')).toBe(false)
            expect(matchPropertyFilter(filter({ operator: 'gte', value: 100 }), 100)).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'lt', value: 100 }), 50)).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'lte', value: 100 }), 100)).toBe(true)
        })
        it('falls back to lexicographic compare when override does not parse', () => {
            expect(matchPropertyFilter(filter({ operator: 'gt', value: 'apple' }), 'banana')).toBe(true)
            expect(matchPropertyFilter(filter({ operator: 'lt', value: 'banana' }), 'apple')).toBe(true)
        })
    })

    describe('missing override', () => {
        it.each(['exact', 'is_not', 'icontains', 'not_icontains', 'regex', 'not_regex', 'gt', 'in'])(
            'returns false for %s when override is undefined or null',
            (op) => {
                expect(matchPropertyFilter(filter({ operator: op, value: 'x' }), undefined)).toBe(false)
                expect(matchPropertyFilter(filter({ operator: op, value: 'x' }), null)).toBe(false)
            }
        )
    })

    describe('unknown / missing operator', () => {
        it('defaults to exact when operator is omitted', () => {
            expect(matchPropertyFilter(filter({ value: 'prod' }), 'prod')).toBe(true)
            expect(matchPropertyFilter(filter({ value: 'prod' }), 'staging')).toBe(false)
        })
        it('returns false for unknown operators (conservative — do not drop)', () => {
            expect(matchPropertyFilter(filter({ operator: 'unsupported_op', value: 'x' }), 'x')).toBe(false)
        })
    })

    describe('missing filter value', () => {
        // Regression guard: without the value-null check, `String(undefined).toLowerCase()`
        // yields `"undefined"` and `icontains` matches every log body containing that string.
        it.each(['exact', 'is_not', 'icontains', 'not_icontains', 'regex', 'not_regex', 'gt', 'in'])(
            'returns false for %s when filter value is undefined',
            (op) => {
                expect(matchPropertyFilter(filter({ operator: op }), 'undefined')).toBe(false)
                expect(matchPropertyFilter(filter({ operator: op }), 'anything')).toBe(false)
            }
        )
        it.each(['exact', 'is_not', 'icontains', 'not_icontains', 'regex', 'not_regex', 'gt', 'in'])(
            'returns false for %s when filter value is null',
            (op) => {
                expect(matchPropertyFilter(filter({ operator: op, value: null }), 'undefined')).toBe(false)
                expect(matchPropertyFilter(filter({ operator: op, value: null }), 'anything')).toBe(false)
            }
        )
    })

    describe('pre-compiled regex', () => {
        it('uses the leaf _compiledRegex when present and skips ad-hoc compile', () => {
            const compiled = compileLeafRegex('precompiled')
            // Set `value` to a different pattern so it's clear the compiled regex won.
            expect(
                matchPropertyFilter(
                    { ...filter({ operator: 'regex', value: 'ad-hoc' }), _compiledRegex: compiled },
                    'precompiled body'
                )
            ).toBe(true)
        })
        it('treats _compiledRegex === null as "compile failed, never match"', () => {
            expect(
                matchPropertyFilter(
                    { ...filter({ operator: 'regex', value: 'whatever' }), _compiledRegex: null },
                    'whatever'
                )
            ).toBe(false)
            expect(
                matchPropertyFilter(
                    { ...filter({ operator: 'not_regex', value: 'whatever' }), _compiledRegex: null },
                    'whatever'
                )
            ).toBe(false)
        })
    })
})
