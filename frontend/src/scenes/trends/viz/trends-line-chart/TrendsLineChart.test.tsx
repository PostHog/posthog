import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom } from 'lib/hog-charts/test-helpers'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, personsModal, renderInsight } from '~/test/insight-testing'
import { createTooltipAccessor } from '~/test/insight-testing/tooltip-helpers'
import { ChartDisplayType } from '~/types'

let cleanupJsdom: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
})

afterEach(() => {
    personsModal.cleanupAll()
    cleanupJsdom()
    cleanup()
})

const HOG_CHARTS_FLAG = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS]: true }

describe('TrendsLineChart', () => {
    describe('tooltips', () => {
        it('shows the series value and glyph for a single series', async () => {
            renderInsight({ query: buildTrendsQuery(), featureFlags: HOG_CHARTS_FLAG })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.element.querySelector('.graph-series-glyph')).toBeInTheDocument()
        })

        it('shows each series with its own value for multiple series', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.row('Napped')).toContain('5')

            const glyphs = tooltip.element.querySelectorAll('.graph-series-glyph')
            expect(glyphs.length).toBe(2)
        })

        it('shows breakdown values in the tooltip', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            // Breakdown data produces multiple series, so the chart requires a
            // click to pin the tooltip (hover alone won't render it).
            await chart.clickAtIndex(2)

            const tooltip = createTooltipAccessor(chart.getTooltip()!)
            expect(tooltip.row('Spike')).toContain('3')
        })

        it('shows current and previous period rows in compare mode', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    compareFilter: { compare: true },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Current')).toContain('134')
            expect(tooltip.row('Previous')).toContain('100')
        })

        it('formats values as percentages in percent stack view', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsAreaGraph,
                        showPercentStackView: true,
                    },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toMatch(/%/)
        })

        it('hides series glyph for formula insights', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { formula: 'A + B' },
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.element.querySelector('.graph-series-glyph')).not.toBeInTheDocument()
        })

        it('shows zero-count series alongside active ones', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'ZeroCounts', name: 'ZeroCounts' }],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('ActiveSeries')).toContain('3')
            expect(tooltip.row('EmptySeries')).toContain('0')
        })

        it('renders correctly when series has no action metadata', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Minimal', name: 'Minimal' }],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(0)

            expect(tooltip.row('Minimal')).toContain('1')
        })
    })

    describe('moving average overlay', () => {
        it('adds a dashed moving-average series per result when enabled', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: {
                        showMovingAverage: true,
                        movingAverageIntervals: 3,
                    },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            // One data series + one moving-average overlay = 2 rendered series.
            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })
        })

        it('omits the moving-average series from tooltip rows', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: {
                        showMovingAverage: true,
                        movingAverageIntervals: 3,
                    },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.element.textContent).not.toContain('Moving avg')
        })

        it('renders only the main series when disabled', async () => {
            renderInsight({ query: buildTrendsQuery(), featureFlags: HOG_CHARTS_FLAG })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 1 data series/i })).toBeInTheDocument()
            })
        })
    })

    describe('click → persons modal', () => {
        it('single series: direct click shows the actors for the clicked day', async () => {
            renderInsight({ query: buildTrendsQuery(), featureFlags: HOG_CHARTS_FLAG })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['pageview-wed-a@example.com', 'pageview-wed-b@example.com'])
            })
            expect(personsModal.title()).toMatch(/12 Jun/)
        })

        it('multi-series: first click pins the tooltip without opening the modal', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await chart.clickAtIndex(2)

            expect(chart.getTooltip()).toBeInTheDocument()
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        it.each([
            ['Spike', ['spike-fan@example.com']],
            ['Bramble', ['bramble-fan@example.com']],
            ['Thistle', ['thistle-fan@example.com']],
        ] as const)('multi-series: clicking the %s row shows only %s actors', async (breakdown, expectedActors) => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await chart.clickAtIndex(2)
            await chart.clickTooltipRow(breakdown)

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(expectedActors)
            })
        })
    })
})
