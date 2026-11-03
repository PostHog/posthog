import { getDotMatrixCellCount, normalizeDotMatrixData } from 'lib/components/DotMatrix/dotMatrixData'

import type { AccountActivityMatrixResult } from '~/queries/schema/schema-general'

import { getAccountActivityMatrixProps, keepKnownSeries } from './accountActivityMatrix'

const RESULT: AccountActivityMatrixResult = {
    rows: [{ key: 'person-ana', label: 'ana@example.com' }],
    columns: [
        { key: '2026-10-18', partial: false },
        { key: '2026-10-25', partial: true },
    ],
    series: [
        { key: 'metric-insights', label: 'Insights' },
        { key: 'metric-replay', label: 'Replay' },
    ],
    data: [
        { row: 'person-ana', column: '2026-10-25', series: 'metric-insights', value: 3 },
        { row: 'person-ana', column: '2026-10-25', series: 'metric-replay', value: 1 },
    ],
    truncated: false,
    skippedMetricIds: [],
}

describe('accountActivityMatrix', () => {
    it('labels weeks, colors each metric, and counts a person once across selected metrics', () => {
        const selected = ['metric-insights', 'metric-replay']
        const props = getAccountActivityMatrixProps(RESULT, selected)
        const cell = normalizeDotMatrixData(props).getCell('person-ana', '2026-10-25')

        expect(props.columns?.map(({ label, partial }) => [label, partial])).toEqual([
            ['Oct 18', false],
            ['Oct 25', true],
        ])
        expect(new Set(props.series?.map(({ color }) => color)).size).toBe(2)
        expect(
            getDotMatrixCellCount(cell, { selectedSeries: selected, aggregateSelection: props.aggregateSelection })
        ).toBe(1)
    })

    it('drops selected keys for metrics the response no longer has', () => {
        expect(keepKnownSeries(['metric-replay', 'metric-deleted'], RESULT)).toEqual(['metric-replay'])
    })

    it('lowers the first dot threshold so a fractional weekly total still draws a dot', () => {
        const fractional = { ...RESULT, data: [{ ...RESULT.data[0], value: 0.5 }] }
        expect(getAccountActivityMatrixProps(fractional, []).sizeThresholds).toEqual([0.5, 5, 10])
    })
})
