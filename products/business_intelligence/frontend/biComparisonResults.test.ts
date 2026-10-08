import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIComparisonRows, getBIComparisonValues } from './biComparisonResults'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { getBIVisualizationResponse } from './biQueryResults'

it.each([
    ['positive', 150, 100, 50, 0.5],
    ['negative', -50, -100, 50, 0.5],
    ['zero baseline', 10, 0, 10, null],
    ['missing baseline', 10, null, null, null],
    ['missing current', null, 10, null, null],
] as const)(
    'compares KPI values with a %s baseline without inventing missing values',
    (_name, current, previous, change, percent) => {
        const config = {
            ...DEFAULT_BI_CONFIG,
            source: { table: 'events' },
            dateRange: { date_from: '-7d' },
            compareFilter: { compare: true },
            chartType: ChartDisplayType.BoldNumber,
        }
        expect(buildBIQuery(config)!.query).toContain('Previous period')
        const rows = buildBIComparisonRows(
            config,
            ['count', 'bi_comparison'],
            [
                [previous, 'Previous period'],
                [current, 'Current period'],
            ]
        )
        expect(rows).toHaveLength(1)
        expect(getBIComparisonValues(rows[0], 'count')).toEqual({ current, previous, change, percent })
    }
)

it('pairs comparison rows by dimensions and preserves periods that only have one side', () => {
    const config = {
        ...DEFAULT_BI_CONFIG,
        compareFilter: { compare: true },
        rows: [
            { id: 'event', expression: 'event', name: 'event', source: { table: 'events' }, type: 'string' as const },
        ],
    }
    const rows = buildBIComparisonRows(
        config,
        ['bi_row_event', 'count', 'bi_comparison'],
        [
            ['purchase', 10, 'Previous period'],
            ['signup', 3, 'Current period'],
            ['purchase', 15, 'Current period'],
            ['old', 4, 'Previous period'],
        ]
    )
    expect(rows.map((row) => [row.dimensions[0], getBIComparisonValues(row, 'count').change])).toEqual([
        ['purchase', 5],
        ['signup', null],
        ['old', null],
    ])
    expect(rows[0].previous?.bi_comparison).toBe('Previous period')
})

it.each([true, false])('trims the probe by whole dimension groups (both periods present: %s)', (bothPeriods) => {
    const config = {
        ...DEFAULT_BI_CONFIG,
        limit: 100 as const,
        compareFilter: { compare: true },
        rows: [
            { id: 'event', expression: 'event', name: 'event', source: { table: 'events' }, type: 'string' as const },
        ],
    }
    const current = Array.from({ length: 51 }, (_, index) => [
        index === 0 ? null : `group ${index}`,
        20,
        'Current period',
    ])
    const previous = bothPeriods ? current.map(([group]) => [group, 10, 'Previous period']) : []
    const response = getBIVisualizationResponse(
        { kind: NodeKind.BIVisualizationNode, config } as BIVisualizationNode,
        {
            columns: ['bi_row_event', 'count', 'bi_comparison'],
            results: [...current, ...previous],
        } as HogQLQueryResponse
    ) as HogQLQueryResponse
    const rows = buildBIComparisonRows(config, response.columns ?? [], response.results)
    expect(rows).toHaveLength(50)
    expect(rows[0].dimensions).toEqual([null])
    expect(getBIComparisonValues(rows[49], 'count')).toMatchObject({
        current: 20,
        previous: bothPeriods ? 10 : null,
        change: bothPeriods ? 10 : null,
    })
    expect(response.hasMore).toBe(true)
})
