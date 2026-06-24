import { fireEvent } from '@testing-library/react'

import type { ChartTheme, Series, TooltipContext } from '../../core/types'
import { getHogChart, renderHogChart } from '../../testing'
import { sortSlopeTooltipRows, type SlopeSeriesMeta } from './slope-data'
import { SlopeChart } from './SlopeChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const LABELS = ['Before', 'After']

const SERIES: Series<SlopeSeriesMeta>[] = [
    { key: 'a', label: 'A', data: [10, 90] },
    { key: 'b', label: 'B', data: [80, 20] },
]

describe('SlopeChart', () => {
    it('renders the two columns and hides the value axis by default', () => {
        const { chart } = renderHogChart(<SlopeChart series={SERIES} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
        expect(chart.xTicks()).toEqual(['Before', 'After'])
        expect(chart.yTicks()).toHaveLength(0)
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<SlopeChart series={[]} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
        expect(chart.slopeValueLabels()).toHaveLength(0)
    })

    it('skips excluded series everywhere', () => {
        const series: Series<SlopeSeriesMeta>[] = [
            ...SERIES,
            {
                key: 'c',
                label: 'C',
                data: [5, 9],
                visibility: { excluded: true },
            },
        ]
        const { chart } = renderHogChart(
            <SlopeChart series={series} labels={LABELS} config={{ legend: { show: true } }} theme={THEME} />
        )
        expect(chart.seriesCount).toBe(2)
        expect(chart.slopeSeriesLabels()).not.toContain('C')
        expect(chart.slopeLegendItems().map((i) => i.label)).not.toContain('C')
    })

    describe('value labels', () => {
        it('shows both start and end value labels for every series by default', () => {
            const { chart } = renderHogChart(<SlopeChart series={SERIES} labels={LABELS} theme={THEME} />)
            const labels = chart.slopeValueLabels()
            expect(
                labels
                    .filter((l) => l.side === 'start')
                    .map((l) => l.text)
                    .sort()
            ).toEqual(['10', '80'])
            expect(
                labels
                    .filter((l) => l.side === 'end')
                    .map((l) => l.text)
                    .sort()
            ).toEqual(['20', '90'])
        })

        it.each([
            ['showStartLabels: false', { showStartLabels: true } as const, { showStartLabel: false }, 'start'],
            ['showEndLabels: false', { showEndLabels: true } as const, { showEndLabel: false }, 'end'],
        ])('honors per-series %s via meta', (_label, config, metaOverride, side) => {
            const series: Series<SlopeSeriesMeta>[] = [
                {
                    key: 'a',
                    label: 'A',
                    data: [10, 90],
                    meta: metaOverride,
                },
                { key: 'b', label: 'B', data: [80, 20] },
            ]
            const { chart } = renderHogChart(
                <SlopeChart series={series} labels={LABELS} theme={THEME} config={config} />
            )
            const sideTexts = chart.slopeValueLabels().filter((l) => l.side === side)
            // The toggled series (`a`) is missing from that column, the other (`b`) remains.
            const aValue = side === 'start' ? '10' : '90'
            expect(sideTexts.map((l) => l.text)).not.toContain(aValue)
            expect(sideTexts).toHaveLength(1)
        })

        it('drops all value labels for a series with visibility.valueLabel false', () => {
            const series: Series<SlopeSeriesMeta>[] = [
                {
                    key: 'a',
                    label: 'A',
                    data: [10, 90],
                    visibility: { valueLabel: false },
                },
                { key: 'b', label: 'B', data: [80, 20] },
            ]
            const { chart } = renderHogChart(<SlopeChart series={series} labels={LABELS} theme={THEME} />)
            const texts = chart.slopeValueLabels().map((l) => l.text)
            expect(texts).toEqual(expect.arrayContaining(['80', '20']))
            expect(texts).not.toContain('10')
            expect(texts).not.toContain('90')
        })

        it('formats values with a custom valueFormatter', () => {
            const { chart } = renderHogChart(
                <SlopeChart series={SERIES} labels={LABELS} config={{ valueFormatter: (v) => `${v}%` }} theme={THEME} />
            )
            expect(chart.slopeValueLabels().every((l) => l.text.endsWith('%'))).toBe(true)
        })
    })

    describe('series labels', () => {
        it('renders a name label per series by default', () => {
            const { chart } = renderHogChart(<SlopeChart series={SERIES} labels={LABELS} theme={THEME} />)
            expect(chart.slopeSeriesLabels().sort()).toEqual(['A', 'B'])
        })

        it('hides all name labels when showSeriesLabels is false', () => {
            const { chart } = renderHogChart(
                <SlopeChart series={SERIES} labels={LABELS} config={{ showSeriesLabels: false }} theme={THEME} />
            )
            expect(chart.slopeSeriesLabels()).toHaveLength(0)
        })

        it('keeps the highest-change name and drops a colliding low-change one', () => {
            // Both end at 100 (same y, same column); the steeper line must win the collision.
            const series: Series<SlopeSeriesMeta>[] = [
                { key: 'big', label: 'Big', data: [0, 100] },
                { key: 'sml', label: 'Small', data: [98, 100] },
            ]
            const { chart } = renderHogChart(<SlopeChart series={series} labels={LABELS} theme={THEME} />)
            expect(chart.slopeSeriesLabels()).toEqual(['Big'])
        })
    })

    describe('legend', () => {
        it('is hidden unless enabled', () => {
            const { chart } = renderHogChart(<SlopeChart series={SERIES} labels={LABELS} theme={THEME} />)
            expect(chart.slopeLegendItems()).toHaveLength(0)
        })

        it('shows the label and signed change for each series', () => {
            const { chart } = renderHogChart(
                <SlopeChart series={SERIES} labels={LABELS} config={{ legend: { show: true } }} theme={THEME} />
            )
            expect(chart.slopeLegendItems()).toEqual([
                { label: 'A', secondaryLabel: '+80' },
                { label: 'B', secondaryLabel: '-60' },
            ])
        })

        it('formats the change with a custom deltaFormatter', () => {
            const { chart } = renderHogChart(
                <SlopeChart
                    series={SERIES}
                    labels={LABELS}
                    config={{
                        legend: { show: true },
                        deltaFormatter: (d) => `${d > 0 ? '↑' : '↓'}${Math.abs(d)}`,
                    }}
                    theme={THEME}
                />
            )
            expect(chart.slopeLegendItems().map((i) => i.secondaryLabel)).toEqual(['↑80', '↓60'])
        })

        it('orders rows biggest-to-smallest by end value', () => {
            // Input order (A, B, C) differs from descending end values (B 90, C 60, A 30).
            const series: Series<SlopeSeriesMeta>[] = [
                { key: 'a', label: 'A', data: [0, 30] },
                { key: 'b', label: 'B', data: [0, 90] },
                { key: 'c', label: 'C', data: [0, 60] },
            ]
            const { chart } = renderHogChart(
                <SlopeChart series={series} labels={LABELS} config={{ legend: { show: true } }} theme={THEME} />
            )
            expect(chart.slopeLegendItems().map((i) => i.label)).toEqual(['B', 'C', 'A'])
        })

        it('toggles a series off and on when its legend row is clicked', () => {
            const { container, chart } = renderHogChart(
                <SlopeChart series={SERIES} labels={LABELS} config={{ legend: { show: true } }} theme={THEME} />
            )
            expect(chart.seriesCount).toBe(2)
            const legend = container.querySelector('[data-attr="hog-chart-slope-legend"]')!
            const buttonFor = (label: string): HTMLButtonElement =>
                Array.from(legend.querySelectorAll('button')).find((b) => b.textContent?.startsWith(label))!

            fireEvent.click(buttonFor('A'))
            expect(getHogChart(container).seriesCount).toBe(1)
            // The toggled-off series stays listed (so it can be restored).
            expect(
                getHogChart(container)
                    .slopeLegendItems()
                    .map((i) => i.label)
            ).toEqual(['A', 'B'])

            fireEvent.click(buttonFor('A'))
            expect(getHogChart(container).seriesCount).toBe(2)
        })
    })

    describe('incompleteEnd', () => {
        it.each([
            [
                'one series with incompleteEnd',
                [
                    {
                        key: 'a',
                        label: 'A',
                        data: [10, 90],
                        meta: { incompleteEnd: true },
                    },
                ] as Series<SlopeSeriesMeta>[],
            ],
            [
                'multiple series, one with incompleteEnd',
                [
                    {
                        key: 'a',
                        label: 'A',
                        data: [10, 90],
                        meta: { incompleteEnd: true },
                    },
                    { key: 'b', label: 'B', data: [80, 20] },
                ] as Series<SlopeSeriesMeta>[],
            ],
        ])('%s: xTicks shows only the two real labels', (_desc, series) => {
            const { chart } = renderHogChart(<SlopeChart series={series} labels={LABELS} theme={THEME} />)
            expect(chart.xTicks()).toEqual(['Before', 'After'])
        })

        it.each([
            [
                'one series with incompleteEnd',
                [
                    {
                        key: 'a',
                        label: 'A',
                        data: [10, 90],
                        meta: { incompleteEnd: true },
                    },
                ] as Series<SlopeSeriesMeta>[],
                [
                    { side: 'start', text: '10' },
                    { side: 'end', text: '90' },
                ],
            ],
            [
                'multiple series, one with incompleteEnd',
                [
                    {
                        key: 'a',
                        label: 'A',
                        data: [10, 90],
                        meta: { incompleteEnd: true },
                    },
                    { key: 'b', label: 'B', data: [80, 20] },
                ] as Series<SlopeSeriesMeta>[],
                [
                    { side: 'start', text: '10' },
                    { side: 'end', text: '90' },
                    { side: 'start', text: '80' },
                    { side: 'end', text: '20' },
                ],
            ],
        ])('%s: value labels read the true start and end values', (_desc, series, expected) => {
            const { chart } = renderHogChart(<SlopeChart series={series} labels={LABELS} theme={THEME} />)
            const labels = chart.slopeValueLabels().map((l) => ({ side: l.side, text: l.text }))
            for (const e of expected) {
                expect(labels).toContainEqual(e)
            }
        })
    })

    describe('full-series reduction', () => {
        it('slopes a >2-point series to its first and last point and labels', () => {
            const series: Series<SlopeSeriesMeta>[] = [{ key: 'a', label: 'A', data: [10, 20, 30, 40] }]
            const labels = ['Jan', 'Feb', 'Mar', 'Apr']
            const { chart } = renderHogChart(<SlopeChart series={series} labels={labels} theme={THEME} />)
            // Only the two ends are shown — interior points and labels are dropped.
            expect(chart.xTicks()).toEqual(['Jan', 'Apr'])
            const values = chart.slopeValueLabels().map((l) => ({ side: l.side, text: l.text }))
            expect(values).toContainEqual({ side: 'start', text: '10' })
            expect(values).toContainEqual({ side: 'end', text: '40' })
        })
    })

    describe('tooltip row sorting', () => {
        const row = (key: string, value: number): TooltipContext['seriesData'][number] => ({
            series: { key, label: key.toUpperCase(), data: [] },
            value,
            color: '#000',
        })

        it.each([
            ['unsorted input', [row('a', 30), row('b', 90), row('c', 60)], [90, 60, 30]],
            ['already sorted descending', [row('a', 90), row('b', 60), row('c', 30)], [90, 60, 30]],
            ['already sorted ascending', [row('a', 30), row('b', 60), row('c', 90)], [90, 60, 30]],
            ['single element', [row('a', 42)], [42]],
        ] as const)('orders rows biggest-to-smallest by value (%s)', (_label, input, expected) => {
            expect(sortSlopeTooltipRows([...input]).map((r) => r.value)).toEqual([...expected])
        })

        it('does not mutate the input array', () => {
            const input = [row('a', 30), row('b', 90)]
            sortSlopeTooltipRows(input)
            expect(input.map((r) => r.value)).toEqual([30, 90])
        })
    })

    it('forwards dataAttr to the chart wrapper', () => {
        const { chart } = renderHogChart(
            <SlopeChart series={SERIES} labels={LABELS} theme={THEME} dataAttr="slope-instance" />
        )
        expect(chart.element.getAttribute('data-attr')).toBe('slope-instance')
    })
})
