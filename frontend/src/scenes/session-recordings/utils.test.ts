import { defaultQuickEmojis } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import {
    filtersFromUniversalFilterGroups,
    getMaskingConfigFromLevel,
    getMaskingLevelFromConfig,
    isSingleEmoji,
} from 'scenes/session-recordings/utils'

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

    describe('masking config', () => {
        it('reads the text masking level independently of image blocking', () => {
            // full text masking still maps to total-privacy when images are not blocked
            expect(getMaskingLevelFromConfig({ maskTextSelector: '*', maskAllInputs: true })).toBe('total-privacy')
            expect(
                getMaskingLevelFromConfig({ maskTextSelector: '*', maskAllInputs: true, blockSelector: 'img' })
            ).toBe('total-privacy')
        })

        it('does not include a block selector in the level config', () => {
            // level config only carries text and input keys, so merging it keeps a project's image choice
            expect(getMaskingConfigFromLevel('total-privacy')).toEqual({ maskTextSelector: '*', maskAllInputs: true })
            expect(getMaskingConfigFromLevel('normal')).not.toHaveProperty('blockSelector')
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
