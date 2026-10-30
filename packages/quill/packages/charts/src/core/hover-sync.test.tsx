import { render } from '@testing-library/react'

import { LineChart } from '../charts/LineChart/LineChart'
import { TimeSeriesLineChart } from '../charts/TimeSeriesLineChart/TimeSeriesLineChart'
import { getChart, renderChart } from '../testing'
import { buildSyncedIndexFinder, ChartHoverSync, useHoverSync } from './hover-sync'

function Probe({ id, labels, hovered }: { id: string; labels: string[]; hovered: string | null }): JSX.Element {
    return <span data-attr={id}>{useHoverSync(labels, hovered)}</span>
}

const DAYS = ['2026-01-01', '2026-01-02', '2026-01-03']

describe('hover-sync', () => {
    it.each([
        ['matches an identical label', DAYS, '2026-01-02', 1],
        // Labels are bucket starts, so a time maps to the bucket it falls in, not the nearest start.
        ['picks the bucket that contains a time', DAYS, '2026-01-02T15:00:00Z', 1],
        ['covers the whole last bucket', DAYS, '2026-01-03T10:00:00Z', 2],
        [
            'covers a last month longer than the one before it',
            ['2026-01-01', '2026-02-01', '2026-03-01'],
            '2026-03-30',
            2,
        ],
        ['reads an offset label as its instant', DAYS, '2026-01-02T22:00:00-05:00', 2],
        ['ignores a date past the last bucket', DAYS, '2026-01-04T00:00:00Z', -1],
        ['ignores a date before the range', DAYS, '2025-12-31', -1],
        ['ignores an unknown category', ['Mon', 'Tue'], 'Wed', -1],
        ['ignores a numeric category that is not a date', ['1', '3'], '2', -1],
    ])('buildSyncedIndexFinder %s', (_, labels, label, expected) => {
        expect(buildSyncedIndexFinder(labels)(label)).toBe(expected)
    })

    it('shares the hovered label with the other charts in the provider, not with the hovered one', () => {
        const ui = (a: string | null, b: string | null): JSX.Element => (
            <ChartHoverSync>
                <Probe id="a" labels={DAYS} hovered={a} />
                <Probe id="b" labels={DAYS} hovered={b} />
            </ChartHoverSync>
        )
        const { container, rerender } = render(ui('2026-01-03', null))
        const index = (id: string): string | null | undefined =>
            container.querySelector(`[data-attr="${id}"]`)?.textContent
        expect([index('a'), index('b')]).toEqual(['-1', '2'])

        // b takes over the hover before a clears its own, so a's clear must not wipe b's.
        rerender(ui('2026-01-03', '2026-01-01'))
        rerender(ui(null, '2026-01-01'))
        expect([index('a'), index('b')]).toEqual(['0', '-1'])

        rerender(ui(null, null))
        expect([index('a'), index('b')]).toEqual(['-1', '-1'])
    })

    it('returns the crosshair to a chart that still holds its label, such as a pinned one', () => {
        const ui = (a: string | null, b: string | null): JSX.Element => (
            <ChartHoverSync>
                <Probe id="a" labels={DAYS} hovered={a} />
                <Probe id="b" labels={DAYS} hovered={b} />
            </ChartHoverSync>
        )
        const { container, rerender } = render(ui('2026-01-03', null))
        rerender(ui('2026-01-03', '2026-01-01'))
        rerender(ui('2026-01-03', null))
        expect(container.querySelector('[data-attr="b"]')?.textContent).toBe('2')
    })

    it('draws the crosshair on the time-series charts in the provider, and not on an opted-out chart', async () => {
        const series = [{ key: 'a', label: 'A', data: [1, 2, 3] }]
        const { container } = renderChart(
            <ChartHoverSync>
                {['source', 'synced'].map((id) => (
                    <div key={id} data-chart={id}>
                        <TimeSeriesLineChart series={series} labels={DAYS} />
                    </div>
                ))}
                <div data-chart="base">
                    <LineChart series={series} labels={DAYS} />
                </div>
            </ChartHoverSync>
        )
        const chart = (id: string): ReturnType<typeof getChart> =>
            getChart(container.querySelector<HTMLElement>(`[data-chart="${id}"]`)!)
        await chart('source').hoverTooltip(1)
        expect([chart('source'), chart('synced'), chart('base')].map((c) => c.syncedIndex())).toEqual([null, 1, null])
    })

    it('leaves a chart with sync turned off out of the provider', () => {
        function Off({ hovered }: { hovered: string | null }): JSX.Element {
            return <span data-attr="off">{useHoverSync(DAYS, hovered, false)}</span>
        }
        const { container } = render(
            <ChartHoverSync>
                <Probe id="a" labels={DAYS} hovered="2026-01-02" />
                <Off hovered={null} />
            </ChartHoverSync>
        )
        expect(container.querySelector('[data-attr="off"]')?.textContent).toBe('-1')
    })

    it('does nothing outside a provider', () => {
        const { container } = render(<Probe id="a" labels={DAYS} hovered="2026-01-01" />)
        expect(container.textContent).toBe('-1')
    })
})
