/**
 * Regression tests for TrendsLineChartD3 and its TrendsTooltip bridge.
 *
 * The module factory below swaps the production ActionsLineGraph (Chart.js) out
 * for TrendsLineChartD3 (hog-charts) when the harness mounts a Trends insight,
 * so we exercise the real hog-charts render path without committing a swap
 * inside Trends.tsx. The hog-charts LineChart itself is swapped for a capture
 * shim via the jest moduleNameMapper entry in jest.config.ts → see
 * frontend/src/test/insight-testing/hog-charts-mock.tsx.
 */
jest.mock('scenes/trends/viz/ActionsLineGraph', () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { TrendsLineChartD3 } = require('./TrendsLineChartD3')
    return {
        ActionsLineGraph: (props: Record<string, unknown>) => <TrendsLineChartD3 {...props} />,
    }
})

import '@testing-library/jest-dom'

import { cleanup, within } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, renderInsightPage, trendsSeries, waitForChart, waitForTooltip } from '~/test/insight-testing'

describe('TrendsLineChartD3 + TrendsTooltip bridge', () => {
    afterEach(cleanup)

    it('renders captured series and labels', async () => {
        renderInsightPage({ query: buildTrendsQuery() })
        const chart = await waitForChart()

        expect(chart.renderer).toBe('hog-charts')
        expect(chart.seriesNames).toEqual(['$pageview'])
        expect(chart.labels).toEqual(trendsSeries.pageviews.labels)
        expect(chart.series(0).data).toEqual(trendsSeries.pageviews.data)
    })

    it('shows series letter and formatted count in tooltip on hover', async () => {
        renderInsightPage({ query: buildTrendsQuery() })
        const chart = await waitForChart()

        chart.hover(2)
        const tooltip = await waitForTooltip()

        // The canned $pageview series has 134 on day index 2 (Wednesday).
        expect(within(tooltip).getByText('134')).toBeInTheDocument()
        // Series letter A is shown for single-series non-breakdown trends.
        expect(tooltip.querySelector('.graph-series-glyph')).toBeInTheDocument()
    })

    it('renders a single-breakdown series with its breakdown value label', async () => {
        // `hedgehog` breakdown against `Napped` returns five series; we filter
        // the response to just Spike so the bridge exercises the single-series
        // breakdown branch (no SeriesLetter, uses getDatumTitle).
        renderInsightPage({
            query: buildTrendsQuery({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
            }),
            mocks: {
                mockResponses: [
                    {
                        match: (q) => q.kind === NodeKind.TrendsQuery,
                        response: {
                            results: [
                                {
                                    action: { id: 'napped', type: 'events', name: 'Napped' },
                                    label: 'Spike',
                                    count: 11,
                                    data: [1, 2, 3, 4, 1],
                                    days: ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14'],
                                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
                                    breakdown_value: 'Spike',
                                },
                            ],
                        } as any,
                    },
                ],
            },
        })
        const chart = await waitForChart()
        chart.hover(1)
        const tooltip = await waitForTooltip()

        // Single breakdown series → uses datum-label-column with getDatumTitle.
        expect(within(tooltip).getByText('Spike')).toBeInTheDocument()
        // No SeriesGlyph when the bridge falls through to the breakdown label.
        expect(tooltip.querySelector('.graph-series-glyph')).not.toBeInTheDocument()
    })

    it('drops zero-count series and preserves stable order for remaining ones', async () => {
        renderInsightPage({
            query: buildTrendsQuery(),
            mocks: {
                mockResponses: [
                    {
                        match: (q) => q.kind === NodeKind.TrendsQuery,
                        response: {
                            results: [
                                {
                                    action: { id: 'a', type: 'events', name: 'A', order: 0 },
                                    label: 'Empty',
                                    count: 0,
                                    data: [0, 0, 0, 0, 0],
                                    days: ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14'],
                                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
                                },
                                {
                                    action: { id: 'b', type: 'events', name: 'B', order: 1 },
                                    label: 'NonEmpty',
                                    count: 10,
                                    data: [1, 2, 3, 2, 2],
                                    days: ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14'],
                                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
                                },
                            ],
                        } as any,
                    },
                ],
            },
        })
        const chart = await waitForChart()

        // Zero-count series dropped from the rendered set.
        expect(chart.seriesNames).toEqual(['NonEmpty'])
        // Meta.order preserves the pre-filter ordinal (1) used by SeriesLetter —
        // this protects the fix in 2877ba6d5e8.
        expect(chart.series(0).meta?.order).toBe(1)
    })

    it('does not crash when series meta is missing', async () => {
        renderInsightPage({
            query: buildTrendsQuery(),
            mocks: {
                mockResponses: [
                    {
                        match: (q) => q.kind === NodeKind.TrendsQuery,
                        response: {
                            // Response includes only the fields that kea pipelines require
                            // (data, days) but deliberately omits action/breakdown_value/compare_label.
                            // This exercises the bridge's extractMeta() against a minimal series.
                            results: [
                                {
                                    label: 'Bare',
                                    count: 5,
                                    data: [1, 1, 1, 1, 1],
                                    days: ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14'],
                                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
                                } as any,
                            ],
                        } as any,
                    },
                ],
            },
        })
        const chart = await waitForChart()
        expect(() => chart.hover(0)).not.toThrow()
        const tooltip = await waitForTooltip()
        expect(tooltip).toBeInTheDocument()
    })
})
