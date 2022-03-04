import { Entity, EntityFilter, FilterType, InsightType } from '~/types'
import { extractObjectDiffKeys, getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

const createFilter = (id?: Entity['id'], name?: string, custom_name?: string): EntityFilter => {
    return {
        custom_name,
        name: name ?? null,
        id: id ?? null,
    }
}

describe('getDisplayNameFromEntityFilter()', () => {
    const paramsToExpected: [EntityFilter, boolean, string | null][] = [
        [createFilter(3, 'name', 'custom_name'), true, 'custom_name'],
        [createFilter(3, 'name', ''), true, 'name'],
        [createFilter(3, 'name', '    '), true, 'name'],
        [createFilter(3, 'name'), true, 'name'],
        [createFilter(3, '', ''), true, '3'],
        [createFilter(3, '  ', '    '), true, '3'],
        [createFilter(3), true, '3'],
        [createFilter('hi'), true, 'hi'],
        [createFilter(), true, null],
        [createFilter(3, 'name', 'custom_name'), false, 'name'],
        [createFilter(3, '  ', 'custom_name'), false, '3'],
    ]

    paramsToExpected.forEach(([filter, isCustom, expected]) => {
        it(`expect "${expected}" for Filter<custom_name="${filter.custom_name}", name="${filter.name}", id="${filter.id}">`, () => {
            expect(getDisplayNameFromEntityFilter(filter, isCustom)).toEqual(expected)
        })
    })
})

describe('extractObjectDiffKeys()', () => {
    const testCases: [string, FilterType, FilterType, string, Record<string, any>][] = [
        [
            'one value',
            { insight: InsightType.TRENDS },
            { insight: InsightType.FUNNELS },
            '',
            { changed_insight: InsightType.TRENDS },
        ],
        [
            'multiple values',
            { insight: InsightType.TRENDS, date_from: '-7d' },
            { insight: InsightType.FUNNELS, date_from: '-7d' },
            '',
            { changed_insight: InsightType.TRENDS },
        ],
        [
            'nested event',
            { insight: InsightType.TRENDS, events: [{ name: 'pageview', math: 'total' }] },
            { insight: InsightType.TRENDS, events: [{ name: 'pageview', math: 'dau' }] },
            '',
            { changed_event_0_math: 'total' },
        ],
        [
            'nested event multiple',
            {
                insight: InsightType.TRENDS,
                events: [
                    { name: 'pageview', math: 'dau' },
                    { name: 'pageview', math: 'total' },
                ],
            },
            {
                insight: InsightType.TRENDS,
                events: [
                    { name: 'pageview', math: 'dau' },
                    { name: 'pageview', math: 'dau' },
                ],
            },
            '',
            { changed_event_1_math: 'total' },
        ],
        [
            'nested action',
            { insight: InsightType.TRENDS, actions: [{ name: 'pageview', math: 'total' }] },
            { insight: InsightType.TRENDS, actions: [{ name: 'pageview', math: 'dau' }] },
            '',
            { changed_action_0_math: 'total' },
        ],
        [
            'nested action',
            { insight: InsightType.TRENDS, actions: undefined, events: [] },
            { insight: InsightType.TRENDS, actions: [], events: undefined },
            '',
            {},
        ],
        [
            'nested action',
            { insight: InsightType.TRENDS, actions: undefined, events: [] },
            { insight: InsightType.TRENDS, actions: [{ name: 'pageview', math: 'dau ' }], events: undefined },
            '',
            { changed_actions_length: 0 },
        ],
    ]

    testCases.forEach(([testName, oldFilter, newFilter, prefix, expected]) => {
        it(`expect ${JSON.stringify(expected)} for ${testName}`, () => {
            expect(extractObjectDiffKeys(oldFilter, newFilter, prefix)).toEqual(expected)
        })
    })
})
