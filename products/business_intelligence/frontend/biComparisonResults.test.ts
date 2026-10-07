import { ChartDisplayType } from '~/types'

import { buildBIComparisonRows, getBIComparisonValues } from './biComparisonResults'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

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
