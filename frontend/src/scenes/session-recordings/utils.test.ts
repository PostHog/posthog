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
            // Recorded URLs are absolute, so an exact pathname value would stop matching once rewritten.
            ['exact pathname: hint only', [pageProperty('$pathname', PropertyOperator.Exact)], true, false],
            // Negated operators compile to arrayExists over the recording's URLs, which asks "some URL
            // doesn't match" rather than "no URL matches". Swapping those would change the result set.
            [
                'negated current URL: hint only',
                [pageProperty('$current_url', PropertyOperator.NotIContains)],
                true,
                false,
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

        it('swaps nested filters and leaves everything else alone', () => {
            const swapped = swapPageFiltersForVisitedPage({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            pageProperty('$current_url'),
                            pageview([pageProperty('$pathname', PropertyOperator.Regex, '^/docs')]),
                            pageProperty('$current_url', PropertyOperator.NotIContains),
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
                    value: '^/docs',
                },
                pageProperty('$current_url', PropertyOperator.NotIContains),
                event('a'),
            ])
        })
    })
})
