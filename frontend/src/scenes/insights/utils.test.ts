import { Entity, EntityFilter, FilterType } from '~/types'
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
        ['one value', { insight: 'TRENDS' }, { insight: 'FUNNELS' }, '', { changed_insight: 'TRENDS' }],
        [
            'multiple values',
            { insight: 'TRENDS', date_from: '-7d' },
            { insight: 'FUNNELS', date_from: '-7d' },
            '',
            { changed_insight: 'TRENDS' },
        ],
        [
            'nested event',
            { insight: 'TRENDS', events: [{ name: 'pageview', math: 'total' }] },
            { insight: 'TRENDS', events: [{ name: 'pageview', math: 'dau' }] },
            '',
            { changed_event_0_math: 'total' },
        ],
        [
            'nested event multiple',
            {
                insight: 'TRENDS',
                events: [
                    { name: 'pageview', math: 'dau' },
                    { name: 'pageview', math: 'total' },
                ],
            },
            {
                insight: 'TRENDS',
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
            { insight: 'TRENDS', actions: [{ name: 'pageview', math: 'total' }] },
            { insight: 'TRENDS', actions: [{ name: 'pageview', math: 'dau' }] },
            '',
            { changed_action_0_math: 'total' },
        ],
        [
            'nested action',
            { insight: 'TRENDS', actions: undefined, events: [] },
            { insight: 'TRENDS', actions: [], events: undefined },
            '',
            {},
        ],
        [
            'nested action',
            { insight: 'TRENDS', actions: undefined, events: [] },
            { insight: 'TRENDS', actions: [{ name: 'pageview', math: 'dau ' }], events: undefined },
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
