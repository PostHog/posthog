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
            ['pathname: hint and swap', [pageProperty('$pathname')], true, true],
            ['pageview scoped by URL: hint and swap', [pageview([pageProperty('$current_url')])], true, true],
            // Recorded URLs are absolute, so an exact pathname value or an anchored pathname pattern
            // would stop matching once rewritten.
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
