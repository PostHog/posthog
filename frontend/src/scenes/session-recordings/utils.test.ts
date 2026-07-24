import { defaultQuickEmojis } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { filtersFromUniversalFilterGroups, isSingleEmoji } from 'scenes/session-recordings/utils'

import { FilterLogicalOperator, RecordingUniversalFilters } from '~/types'

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
})
