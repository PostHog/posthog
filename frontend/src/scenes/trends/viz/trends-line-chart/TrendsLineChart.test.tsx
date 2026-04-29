import '@testing-library/jest-dom'

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom } from 'lib/hog-charts/test-helpers'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, getHogChart, legend, personsModal, renderInsight } from '~/test/insight-testing'
import { buildAnnotation } from '~/test/insight-testing/test-data'
import { createTooltipAccessor } from '~/test/insight-testing/tooltip-helpers'
import { AnnotationScope, ChartDisplayType } from '~/types'

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

        it('uses context.formatCompareLabel to override Current/Previous in compare mode', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    compareFilter: { compare: true },
                }),
                context: {
                    formatCompareLabel: (label) => (label === 'current' ? 'This week' : 'Last week'),
                },
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('This week')).toContain('134')
            expect(tooltip.row('Last week')).toContain('100')
            expect(tooltip.element.textContent).not.toContain('Current')
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

    describe('annotations', () => {
        it('renders an annotation badge when an annotation exists', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mocks: {
                    annotations: [
                        buildAnnotation({
                            scope: AnnotationScope.Project,
                            content: 'Hedgehog spotted',
                            date_marker: '2024-06-12T12:00:00Z',
                        }),
                    ],
                },
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                const badges = document.querySelectorAll('.AnnotationsBadge')
                expect(badges.length).toBeGreaterThan(0)
            })
        })

        it('does not render annotations when inSharedMode is true', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mocks: {
                    annotations: [
                        buildAnnotation({
                            scope: AnnotationScope.Project,
                            content: 'Hidden in shared mode',
                            date_marker: '2024-06-12T12:00:00Z',
                        }),
                    ],
                },
                inSharedMode: true,
                featureFlags: HOG_CHARTS_FLAG,
            })

            await screen.findByRole('img', { name: /chart with/i })
            expect(document.querySelectorAll('.AnnotationsBadge')).toHaveLength(0)
        })
    })

    describe('area chart', () => {
        it('renders the chart in area mode without crashing', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: { display: ChartDisplayType.ActionsAreaGraph },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })
        })

        it('uses percent ticks on the y-axis in percent stack view', async () => {
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

            await screen.findByRole('img', { name: /chart with/i })
            const ticks = getHogChart().yTicks()
            expect(ticks.length).toBeGreaterThan(0)
            for (const t of ticks) {
                expect(t).toMatch(/%/)
            }
        })
    })

    describe('tooltip date title', () => {
        it('shows the hovered day in the tooltip title row', async () => {
            renderInsight({
                query: buildTrendsQuery({ interval: 'day' }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            const tooltip = await chart.hoverTooltip(2)

            // Wednesday is the third day (index 2) in our pageview fixture (2024-06-12).
            expect(tooltip.title()).toMatch(/Wednesday/i)
            expect(tooltip.title()).toMatch(/12.+Jun/)
        })
    })

    describe('tooltip pin lifecycle', () => {
        it.each([
            {
                trigger: 'Escape key press',
                unpin: async () => {
                    fireEvent.keyDown(document, { key: 'Escape' })
                },
            },
            {
                trigger: 'click outside the chart',
                unpin: async () => {
                    // The chart attaches its outside-click listener via setTimeout(0); flush
                    // first so the listener actually intercepts the click.
                    await new Promise((resolve) => setTimeout(resolve, 5))
                    const outside = document.body.appendChild(document.createElement('div'))
                    fireEvent.click(outside)
                    outside.remove()
                },
            },
        ])('unpins on $trigger', async ({ unpin }) => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await chart.clickAtIndex(2)
            expect(chart.getTooltip()).toBeInTheDocument()

            await unpin()

            await waitFor(() => {
                expect(chart.getTooltip()).not.toBeInTheDocument()
            })
        })
    })

    describe('alert overlays', () => {
        it('does not render any alert overlay for an unsaved insight (insight.id is missing)', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await screen.findByRole('img', { name: /chart with/i })
            // Reference lines come exclusively from goalLines in this test (none configured),
            // so the count must be 0 — anything here would be a leaked alert overlay.
            expect(getHogChart().referenceLines()).toHaveLength(0)
        })
    })

    describe('hidden series via legend', () => {
        it('excludes a hidden series from the tooltip', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            // Wait for both series before toggling.
            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })

            await legend.toggle('Napped')

            const tooltip = await chart.hoverTooltip(2)
            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.element.textContent).not.toContain('Napped')
        })

        it('does not draw value labels or trend lines for a hidden series', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: { showValuesOnSeries: true, showTrendLines: true },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                // 2 main + 2 trend lines = 4 series
                expect(screen.getByRole('img', { name: /chart with 4 data series/i })).toBeInTheDocument()
            })

            await legend.toggle('Napped')

            await waitFor(() => {
                // Hiding Napped removes its main series + its trend line.
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })

            // No Napped value labels remain (Napped's data is 1, 3, 5, 8, 2; the 8 was the
            // tallest distinct label so its absence is the cleanest signal).
            const labels = getHogChart()
                .valueLabels()
                .map((l) => l.text)
            expect(labels).not.toContain('8')
            // Pageview labels should still be there.
            expect(labels).toContain('210')
        })
    })

    describe('multi-axis', () => {
        it.each([
            { name: 'renders a right y-axis when showMultipleYAxes is true', enabled: true, expectedRight: true },
            { name: 'omits the right y-axis by default', enabled: false, expectedRight: false },
        ])('$name', async ({ enabled, expectedRight }) => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: enabled ? { showMultipleYAxes: true } : undefined,
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(getHogChart().hasRightAxis).toBe(expectedRight)
            })
            if (expectedRight) {
                expect(getHogChart().yRightTicks().length).toBeGreaterThan(0)
            }
        })
    })

    describe('goal lines', () => {
        // Pageview peaks at 210; a `displayIfCrossed: false` line below that peak is filtered out.
        it.each([
            {
                name: 'single goal line renders with its label',
                goalLines: [{ label: 'Target', value: 150, displayIfCrossed: true }],
                expectedLabels: ['Target'],
            },
            {
                name: 'multiple goal lines render in order',
                goalLines: [
                    { label: 'Floor', value: 50, displayIfCrossed: true },
                    { label: 'Ceiling', value: 200, displayIfCrossed: true },
                ],
                expectedLabels: ['Floor', 'Ceiling'],
            },
            {
                name: 'displayIfCrossed=false hides a line the data has crossed',
                goalLines: [{ label: 'Crossed', value: 100, displayIfCrossed: false }],
                expectedLabels: [],
            },
        ])('$name', async ({ goalLines, expectedLabels }) => {
            renderInsight({
                query: buildTrendsQuery({ trendsFilter: { goalLines } }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await screen.findByRole('img', { name: /chart with/i })
            const lines = getHogChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(expectedLabels)
            for (const line of lines) {
                expect(line.orientation).toBe('horizontal')
            }
        })
    })

    describe('value labels overlay', () => {
        it('renders a value label per non-zero point when showValuesOnSeries is enabled', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { showValuesOnSeries: true },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                const labels = getHogChart().valueLabels()
                expect(labels.length).toBeGreaterThan(0)
            })
            // Pageview series is [45, 82, 134, 210, 95]; all non-zero => 5 labels.
            const labels = getHogChart()
                .valueLabels()
                .map((l) => l.text)
            expect(labels).toContain('45')
            expect(labels).toContain('210')
        })

        it('formats value labels as percentages in percent stack view', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsAreaGraph,
                        showPercentStackView: true,
                        showValuesOnSeries: true,
                    },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(getHogChart().valueLabels().length).toBeGreaterThan(0)
            })
            const labels = getHogChart().valueLabels()
            for (const l of labels) {
                expect(l.text).toMatch(/%/)
            }
        })

        it('renders no labels when showValuesOnSeries is disabled', async () => {
            renderInsight({ query: buildTrendsQuery(), featureFlags: HOG_CHARTS_FLAG })

            await screen.findByRole('img', { name: /chart with/i })
            expect(getHogChart().valueLabels()).toHaveLength(0)
        })
    })

    describe('log y-scale', () => {
        it('renders without crashing when series contain zero values', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'ZeroCounts', name: 'ZeroCounts' }],
                    trendsFilter: { yAxisScaleType: 'log10' },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)
            expect(tooltip.row('ActiveSeries')).toContain('3')
            expect(tooltip.row('EmptySeries')).toContain('0')
        })
    })

    describe('confidence intervals overlay', () => {
        beforeEach(() => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { showConfidenceIntervals: true, confidenceLevel: 95 },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })
        })

        it('adds a CI band series when enabled', async () => {
            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })
        })

        it('omits the CI series from tooltip rows', async () => {
            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.element.textContent).not.toContain('(CI)')
        })
    })

    describe('trend lines overlay', () => {
        beforeEach(() => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { showTrendLines: true },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })
        })

        it('adds a dashed trend-line series when enabled', async () => {
            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })
        })

        it('omits the trend-line series from tooltip rows', async () => {
            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            // The trend-line carries the same series label; only the main
            // row should appear, so there must be exactly one row matching.
            const rows = Array.from(tooltip.element.querySelectorAll('tr')).filter((r) =>
                r.textContent?.includes('Pageview')
            )
            expect(rows).toHaveLength(1)
        })
    })

    describe('trend lines + moving average', () => {
        it('renders separate trend lines for the raw and moving-average series', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: {
                        showTrendLines: true,
                        showMovingAverage: true,
                        movingAverageIntervals: 3,
                    },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            // main + raw trendline + moving avg + moving-avg trendline = 4 series.
            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 4 data series/i })).toBeInTheDocument()
            })
        })
    })

    describe('empty state', () => {
        it('renders InsightEmptyState when all series are zero', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
            })
            expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
        })

        it('uses context.emptyStateHeading override when provided', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
                }),
                context: { emptyStateHeading: 'Nothing to see here, hedgehog' },
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByText('Nothing to see here, hedgehog')).toBeInTheDocument()
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

        it('fires context.onDataPointClick instead of opening the persons modal', async () => {
            const onDataPointClick = jest.fn()
            renderInsight({
                query: buildTrendsQuery(),
                context: { onDataPointClick },
                featureFlags: HOG_CHARTS_FLAG,
            })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(onDataPointClick).toHaveBeenCalledTimes(1)
            })
            const [seriesArg] = onDataPointClick.mock.calls[0]
            expect(seriesArg.day).toBe('2024-06-12')
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        it('does nothing when there is no persons modal and no onDataPointClick', async () => {
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

            await chart.clickAtIndex(2)

            // Without a click handler the canvas still renders; clicking is a no-op.
            expect(personsModal.get()).not.toBeInTheDocument()
        })
    })
})
