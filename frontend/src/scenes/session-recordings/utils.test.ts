import { defaultQuickEmojis } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { filtersFromUniversalFilterGroups, hasPageFilter, isSingleEmoji } from 'scenes/session-recordings/utils'

import { FilterLogicalOperator, PropertyOperator, RecordingUniversalFilters } from '~/types'

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

    describe('hasPageFilter', () => {
        const pageProperty = (
            key: string,
            operator: PropertyOperator = PropertyOperator.IContains,
            value: any = '/pricing'
        ): any => ({ type: 'event', key, operator, value })

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
            ['shows the hint for a current URL property', [pageProperty('$current_url')], true],
            ['shows the hint for a pathname property', [pageProperty('$pathname')], true],
            ['shows the hint for a URL property scoping a pageview', [pageview([pageProperty('$current_url')])], true],
            [
                'shows the hint for a negated URL property',
                [pageProperty('$current_url', PropertyOperator.NotIContains)],
                true,
            ],
            // Nothing is typed yet, so there is no page to nudge about.
            [
                'stays quiet until a value is entered',
                [pageProperty('$current_url', PropertyOperator.IContains, '')],
                false,
            ],
            [
                'stays quiet for an operator that takes no value',
                [pageProperty('$current_url', PropertyOperator.IsSet, null)],
                false,
            ],
            ['stays quiet for a bare pageview', [pageview([])], false],
            ['stays quiet for an unrelated filter', [event('a')], false],
        ])('%s', (_label, values, shows) => {
            expect(hasPageFilter(group(...values))).toBe(shows)
        })
    })
})
