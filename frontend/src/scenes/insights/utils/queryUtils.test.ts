import { NodeKind } from '~/queries/schema/schema-general'

import { transformResponseForSeriesNameChange } from './queryUtils'

const trendsQuery = (
    series: { event?: string; custom_name?: string }[]
): {
    kind: typeof NodeKind.TrendsQuery
    series: { kind: typeof NodeKind.EventsNode; event?: string; custom_name?: string }[]
} => ({
    kind: NodeKind.TrendsQuery as const,
    series: series.map((s) => ({ kind: NodeKind.EventsNode as const, ...s })),
})

interface PartialAction {
    order?: number
    custom_name?: string
    id?: string
    type?: string
    math?: string
}

interface PartialTrendResult {
    action?: PartialAction | null
    label?: string
    breakdown_value?: string
    compare_label?: string
    data?: number[]
    days?: string[]
    count?: number
}

interface TestCase {
    name: string
    response: { results?: PartialTrendResult[] } | Record<string, unknown>
    oldSeries: { event?: string; custom_name?: string }[]
    newSeries: { event?: string; custom_name?: string }[]
    expected?: { results?: PartialTrendResult[] }
    expectedSameReference?: boolean
}

const testCases: TestCase[] = [
    {
        name: 'updates single series custom_name',
        response: {
            results: [{ action: { order: 0, custom_name: 'old' }, label: 'test' }],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expected: {
            results: [{ action: { order: 0, custom_name: 'new' }, label: 'test' }],
        },
    },
    {
        name: 'returns same object when no changes needed',
        response: {
            results: [{ action: { order: 0, custom_name: 'same' }, label: 'test' }],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'same' }],
        newSeries: [{ event: '$pageview', custom_name: 'same' }],
        expectedSameReference: true,
    },
    {
        name: 'handles renaming from undefined to a value',
        response: {
            results: [{ action: { order: 0 }, label: '$pageview' }],
        },
        oldSeries: [{ event: '$pageview' }],
        newSeries: [{ event: '$pageview', custom_name: 'My Custom Name' }],
        expected: {
            results: [{ action: { order: 0, custom_name: 'My Custom Name' }, label: '$pageview' }],
        },
    },
    {
        name: 'handles clearing custom_name (value to undefined)',
        response: {
            results: [{ action: { order: 0, custom_name: 'old name' }, label: '$pageview' }],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old name' }],
        newSeries: [{ event: '$pageview', custom_name: undefined }],
        expected: {
            results: [{ action: { order: 0, custom_name: undefined }, label: '$pageview' }],
        },
    },
    {
        name: 'updates multiple series independently',
        response: {
            results: [
                { action: { order: 0, custom_name: 'A' }, label: 'first' },
                { action: { order: 1, custom_name: 'B' }, label: 'second' },
            ],
        },
        oldSeries: [
            { event: '$pageview', custom_name: 'A' },
            { event: '$autocapture', custom_name: 'B' },
        ],
        newSeries: [
            { event: '$pageview', custom_name: 'A-renamed' },
            { event: '$autocapture', custom_name: 'B' },
        ],
        expected: {
            results: [
                { action: { order: 0, custom_name: 'A-renamed' }, label: 'first' },
                { action: { order: 1, custom_name: 'B' }, label: 'second' },
            ],
        },
    },
    {
        name: 'handles multiple results per series (breakdowns) - all get same custom_name',
        response: {
            results: [
                { action: { order: 0, custom_name: 'A' }, breakdown_value: 'Chrome' },
                { action: { order: 0, custom_name: 'A' }, breakdown_value: 'Firefox' },
                { action: { order: 0, custom_name: 'A' }, breakdown_value: 'Safari' },
                { action: { order: 1, custom_name: 'B' }, breakdown_value: 'Chrome' },
            ],
        },
        oldSeries: [
            { event: '$pageview', custom_name: 'A' },
            { event: '$autocapture', custom_name: 'B' },
        ],
        newSeries: [
            { event: '$pageview', custom_name: 'A-renamed' },
            { event: '$autocapture', custom_name: 'B' },
        ],
        expected: {
            results: [
                { action: { order: 0, custom_name: 'A-renamed' }, breakdown_value: 'Chrome' },
                { action: { order: 0, custom_name: 'A-renamed' }, breakdown_value: 'Firefox' },
                { action: { order: 0, custom_name: 'A-renamed' }, breakdown_value: 'Safari' },
                { action: { order: 1, custom_name: 'B' }, breakdown_value: 'Chrome' },
            ],
        },
    },
    {
        name: 'skips formula results (action is null)',
        response: {
            results: [
                { action: null, label: 'Formula (A+B)' },
                { action: { order: 0, custom_name: 'old' }, label: 'test' },
            ],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expected: {
            results: [
                { action: null, label: 'Formula (A+B)' },
                { action: { order: 0, custom_name: 'new' }, label: 'test' },
            ],
        },
    },
    {
        name: 'handles out-of-bounds order gracefully (leaves unchanged)',
        response: {
            results: [{ action: { order: 5, custom_name: 'old' }, label: 'test' }],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expected: {
            results: [{ action: { order: 5, custom_name: 'old' }, label: 'test' }],
        },
    },
    {
        name: 'returns same reference for empty results array',
        response: { results: [] },
        oldSeries: [{ event: '$pageview' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expectedSameReference: true,
    },
    {
        name: 'returns same reference when results property is missing',
        response: {},
        oldSeries: [{ event: '$pageview' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expectedSameReference: true,
    },
    {
        name: 'returns same reference when results is not an array',
        response: { results: 'not an array' },
        oldSeries: [{ event: '$pageview' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expectedSameReference: true,
    },
    {
        name: 'preserves other action properties when updating custom_name',
        response: {
            results: [
                {
                    action: {
                        order: 0,
                        custom_name: 'old',
                        id: '$pageview',
                        type: 'events',
                        math: 'total',
                    },
                    label: 'test',
                },
            ],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expected: {
            results: [
                {
                    action: {
                        order: 0,
                        custom_name: 'new',
                        id: '$pageview',
                        type: 'events',
                        math: 'total',
                    },
                    label: 'test',
                },
            ],
        },
    },
    {
        name: 'preserves other result properties when updating',
        response: {
            results: [
                {
                    action: { order: 0, custom_name: 'old' },
                    label: 'test',
                    data: [1, 2, 3],
                    days: ['2024-01-01', '2024-01-02', '2024-01-03'],
                    count: 6,
                },
            ],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expected: {
            results: [
                {
                    action: { order: 0, custom_name: 'new' },
                    label: 'test',
                    data: [1, 2, 3],
                    days: ['2024-01-01', '2024-01-02', '2024-01-03'],
                    count: 6,
                },
            ],
        },
    },
    {
        name: 'handles compare mode (current/previous share same order)',
        response: {
            results: [
                { action: { order: 0, custom_name: 'old' }, compare_label: 'current' },
                { action: { order: 0, custom_name: 'old' }, compare_label: 'previous' },
            ],
        },
        oldSeries: [{ event: '$pageview', custom_name: 'old' }],
        newSeries: [{ event: '$pageview', custom_name: 'new' }],
        expected: {
            results: [
                { action: { order: 0, custom_name: 'new' }, compare_label: 'current' },
                { action: { order: 0, custom_name: 'new' }, compare_label: 'previous' },
            ],
        },
    },
    {
        name: 'handles empty series array',
        response: {
            results: [{ action: { order: 0, custom_name: 'old' }, label: 'test' }],
        },
        oldSeries: [],
        newSeries: [],
        expectedSameReference: true,
    },
]

describe('transformResponseForSeriesNameChange', () => {
    it.each(testCases)('$name', ({ response, oldSeries, newSeries, expected, expectedSameReference }) => {
        const oldQuery = trendsQuery(oldSeries)
        const newQuery = trendsQuery(newSeries)
        const result = transformResponseForSeriesNameChange(response as any, oldQuery, newQuery)

        if (expectedSameReference) {
            expect(result).toBe(response)
        } else if (expected) {
            expect(result).toEqual(expect.objectContaining(expected))
        }
    })
})
