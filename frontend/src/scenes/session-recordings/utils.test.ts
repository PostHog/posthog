import { defaultQuickEmojis } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import {
    canSwapPageFiltersForVisitedPage,
    filtersFromUniversalFilterGroups,
    hasPageFilter,
    isSingleEmoji,
    swapPageFiltersForVisitedPage,
} from 'scenes/session-recordings/utils'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFiltersGroup,
} from '~/types'

const withFilterGroup = (filterGroup: RecordingUniversalFilters['filter_group']): RecordingUniversalFilters => ({
    date_from: '-3d',
    date_to: null,
    filter_test_accounts: false,
    duration: [],
    filter_group: filterGroup,
})

const event = (name: string): any => ({ id: name, name, type: 'events' })

describe('session recording utils', () => {
    defaultQuickEmojis.forEach((quickEmoji) => {
        it(`can check ${quickEmoji} is a single emoji`, () => {
            expect(isSingleEmoji(quickEmoji)).toBe(true)
        })
        it(`can check ${quickEmoji}${quickEmoji} is not a single emoji`, () => {
            expect(isSingleEmoji(`${quickEmoji}${quickEmoji}`)).toBe(false)
        })
    })

    describe('filtersFromUniversalFilterGroups', () => {
        it.each([
            [
                'canonical values: [{ values: [...] }] shape',
                {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [event('a'), event('b'), event('c')] }],
                },
                [event('a'), event('b'), event('c')],
            ],
            [
                'broken per-event-group top-level shape seen in some saved filters',
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        { type: FilterLogicalOperator.And, values: [] },
                        { type: FilterLogicalOperator.And, values: [event('a')] },
                        { type: FilterLogicalOperator.And, values: [event('b')] },
                    ],
                },
                [event('a'), event('b')],
            ],
        ])('returns all leaves for the %s', (_label, filterGroup, expected) => {
            expect(filtersFromUniversalFilterGroups(withFilterGroup(filterGroup))).toEqual(expected)
        })
    })

    describe('steering page filters to visited_page', () => {
        const pageProperty = (
            key: string,
            operator: PropertyOperator = PropertyOperator.IContains,
            value: any = '/pricing'
        ): any => ({ type: PropertyFilterType.Event, key, operator, value })

        const pageview = (properties: any[]): any => ({
            id: '$pageview',
            name: '$pageview',
            type: 'events',
            properties,
        })

        const group = (...values: any[]): RecordingUniversalFilters =>
            withFilterGroup({
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values }],
            })

        it.each([
            ['current URL: hint and swap', [pageProperty('$current_url')], true, true],
            ['pageview scoped by URL: hint and swap', [pageview([pageProperty('$current_url')])], true, true],
            // `visited_page` matches the full recorded URL, but `$pathname` is the path alone, so no
            // rewrite is safe: an exact or anchored value stops matching, and a substring can collide
            // with the host, query, or fragment. Every pathname operator gets the hint but no swap.
            ['pathname substring: hint only', [pageProperty('$pathname')], true, false],
            ['exact pathname: hint only', [pageProperty('$pathname', PropertyOperator.Exact)], true, false],
            ['is-not pathname: hint only', [pageProperty('$pathname', PropertyOperator.IsNot)], true, false],
            ['regex pathname: hint only', [pageProperty('$pathname', PropertyOperator.Regex, '^/docs')], true, false],
            [
                'not-regex pathname: hint only',
                [pageProperty('$pathname', PropertyOperator.NotRegex, '^/docs')],
                true,
                false,
            ],
            // A negated entity means "sessions without any matching pageview"; a positive visited_page inverts it.
            [
                'negated pageview scoped by URL: hint only',
                [{ ...pageview([pageProperty('$current_url')]), negation: true }],
                true,
                false,
            ],
            // Inside a match-all group the backend excludes the whole session, so both sides mean
            // "no URL matches". These swaps stop being offered inside match-any groups (see below).
            [
                'negated current URL: hint and swap',
                [pageProperty('$current_url', PropertyOperator.NotIContains)],
                true,
                true,
            ],
            [
                'negated regex current URL: hint and swap',
                [pageProperty('$current_url', PropertyOperator.NotRegex)],
                true,
                true,
            ],
            [
                'valueless current URL: neither',
                [pageProperty('$current_url', PropertyOperator.IsSet, null)],
                false,
                false,
            ],
            ['bare pageview: neither', [pageview([])], false, false],
            [
                'pageview scoped by URL and something else: hint only',
                [pageview([pageProperty('$current_url'), pageProperty('$browser', PropertyOperator.Exact, 'Chrome')])],
                true,
                false,
            ],
            ['unrelated filter: neither', [event('a')], false, false],
        ])('%s', (_label, values, shows, swappable) => {
            expect(hasPageFilter(group(...values))).toBe(shows)
            expect(canSwapPageFiltersForVisitedPage(group(...values))).toBe(swappable)
        })

        it('does not show the hint before a value is entered', () => {
            expect(hasPageFilter(group(pageProperty('$current_url', PropertyOperator.IContains, '')))).toBe(false)
        })

        it('only swaps negated operators when every group matches all filters', () => {
            const orGroup = (...values: any[]): RecordingUniversalFilters =>
                withFilterGroup({
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.Or, values }],
                })

            expect(canSwapPageFiltersForVisitedPage(orGroup(pageProperty('$current_url')))).toBe(true)

            const negated = pageProperty('$current_url', PropertyOperator.NotIContains)
            expect(hasPageFilter(orGroup(negated))).toBe(true)
            expect(canSwapPageFiltersForVisitedPage(orGroup(negated))).toBe(false)
            expect(canSwapPageFiltersForVisitedPage(orGroup(pageview([negated])))).toBe(false)
        })

        it('does not swap a match-any group that mixes page filters with other filters', () => {
            const orGroup = (...values: any[]): RecordingUniversalFilters =>
                withFilterGroup({
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.Or, values }],
                })

            // visited_page lands in the always-AND'd HAVING, so swapping one branch of an OR
            // turns the union with the remaining event filter into an intersection.
            const mixed = orGroup(pageProperty('$current_url'), event('a'))
            expect(hasPageFilter(mixed)).toBe(true)
            expect(canSwapPageFiltersForVisitedPage(mixed)).toBe(false)

            // All members swap together, so the OR survives among the visited_page predicates.
            expect(
                canSwapPageFiltersForVisitedPage(
                    orGroup(pageProperty('$current_url'), pageview([pageProperty('$current_url')]))
                )
            ).toBe(true)
        })

        it('does not swap when a non-page filter shares the tree with any OR group', () => {
            // deriveOperand turns the whole query OR as soon as one group is OR, so a non-page sibling
            // stays in WHERE and gets AND'd against the swapped visited_page HAVING predicate, turning
            // the union into an intersection. Both shapes below are reachable: a "match any" scanner
            // round-trips to an OR outer group wrapping a hard-coded inner AND group.
            const browser = pageProperty('$browser', PropertyOperator.Exact, 'Chrome')

            const orWrappingAndSibling = withFilterGroup({
                type: FilterLogicalOperator.Or,
                values: [{ type: FilterLogicalOperator.And, values: [pageProperty('$current_url'), browser] }],
            })
            expect(hasPageFilter(orWrappingAndSibling)).toBe(true)
            expect(canSwapPageFiltersForVisitedPage(orWrappingAndSibling)).toBe(false)

            const orPageGroupBesideSibling = withFilterGroup({
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.Or, values: [pageProperty('$current_url')] }, browser],
            })
            expect(hasPageFilter(orPageGroupBesideSibling)).toBe(true)
            expect(canSwapPageFiltersForVisitedPage(orPageGroupBesideSibling)).toBe(false)
        })

        it('does not swap a pageview scoped by a negated URL property even under match-all', () => {
            // Pre-swap this still requires a pageview to exist ("has a pageview whose URL doesn't
            // match"); a bare negated visited_page has no such requirement.
            const negatedScoped = pageview([pageProperty('$current_url', PropertyOperator.NotIContains)])
            expect(hasPageFilter(group(negatedScoped))).toBe(true)
            expect(canSwapPageFiltersForVisitedPage(group(negatedScoped))).toBe(false)
        })

        it('swaps nested filters and leaves everything else alone', () => {
            const swapped = swapPageFiltersForVisitedPage({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            pageProperty('$current_url'),
                            pageview([pageProperty('$current_url', PropertyOperator.Regex, 'posthog.com/docs')]),
                            pageview([pageProperty('$pathname', PropertyOperator.Regex, '^/docs')]),
                            pageProperty('$current_url', PropertyOperator.NotIContains),
                            pageProperty('$pathname', PropertyOperator.Exact),
                            event('a'),
                        ],
                    },
                ],
            })

            expect((swapped.values[0] as UniversalFiltersGroup).values).toEqual([
                {
                    type: PropertyFilterType.Recording,
                    key: 'visited_page',
                    operator: PropertyOperator.IContains,
                    value: '/pricing',
                },
                {
                    type: PropertyFilterType.Recording,
                    key: 'visited_page',
                    operator: PropertyOperator.Regex,
                    value: 'posthog.com/docs',
                },
                pageview([pageProperty('$pathname', PropertyOperator.Regex, '^/docs')]),
                {
                    type: PropertyFilterType.Recording,
                    key: 'visited_page',
                    operator: PropertyOperator.NotIContains,
                    value: '/pricing',
                },
                pageProperty('$pathname', PropertyOperator.Exact),
                event('a'),
            ])
        })
    })
})
