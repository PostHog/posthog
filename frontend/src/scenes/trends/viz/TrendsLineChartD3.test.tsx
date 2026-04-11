import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom } from 'lib/hog-charts/test-helpers'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

let cleanupJsdom: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
})

afterEach(() => {
    cleanupJsdom()
    cleanup()
})

const HOG_CHARTS_FLAG = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS]: true }

describe.skip('TrendsLineChartD3', () => {
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

            const tooltip = await chart.hoverTooltip(2)

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

        it('excludes zero-count series', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'ZeroCounts', name: 'ZeroCounts' }],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('ActiveSeries')).toContain('3')
            expect(tooltip.row('EmptySeries')).toBeUndefined()
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
})
