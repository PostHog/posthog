import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom } from 'lib/hog-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'
import { buildAnnotation } from '~/test/insight-testing/test-data'
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

const HOG_CHARTS_FLAG = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_BAR]: true }
const trendsBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
    buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsBar }, ...extra })

describe('TrendsBarChart (ActionsBar)', () => {
    it.each([
        { name: 'one series for a single event', query: trendsBar(), expected: 1 },
        {
            name: 'one series per breakdown value',
            query: trendsBar({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
            }),
            expected: 5,
        },
    ])('renders $name', async ({ query, expected }) => {
        renderInsight({ query, featureFlags: HOG_CHARTS_FLAG })

        await waitFor(() => {
            expect(
                screen.getByRole('img', { name: new RegExp(`chart with ${expected} data series`, 'i') })
            ).toBeInTheDocument()
        })
    })

    it('shows the series value in the tooltip on hover', async () => {
        renderInsight({ query: trendsBar(), featureFlags: HOG_CHARTS_FLAG })

        const tooltip = await chart.hoverTooltip(2)
        expect(tooltip.row('Pageview')).toContain('134')
    })

    it('opens the persons modal on click for a single series', async () => {
        renderInsight({ query: trendsBar(), featureFlags: HOG_CHARTS_FLAG })

        await chart.clickAtIndex(2)

        await waitFor(() => {
            expect(personsModal.actorNames()).toEqual(['pageview-wed-a@example.com', 'pageview-wed-b@example.com'])
        })
        expect(personsModal.title()).toMatch(/12 Jun/)
    })

    it('renders InsightEmptyState when all series are zero', async () => {
        renderInsight({
            query: trendsBar({
                series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
        })
        expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
    })

    it('shows current and previous period rows in compare mode', async () => {
        renderInsight({
            query: trendsBar({ compareFilter: { compare: true } }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
        })

        const tooltip = await chart.hoverTooltip(2)

        // Stacked bars surface stacked-top values in tooltip rows, not raw series values, so we
        // only assert that both compare rows are present — the dimming is enforced by the
        // transforms unit test.
        expect(tooltip.row('Current')).toBeTruthy()
        expect(tooltip.row('Previous')).toBeTruthy()
    })

    it('formats values as percentages in percent stack view', async () => {
        renderInsight({
            query: trendsBar({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
                trendsFilter: { display: ChartDisplayType.ActionsBar, showPercentStackView: true },
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        const tooltip = await chart.hoverTooltip(2)

        expect(tooltip.row('Pageview')).toMatch(/%/)
    })
})

describe('TrendsBarChart (ActionsBarValue)', () => {
    const aggregatedBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
        buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsBarValue }, ...extra })

    it('renders without crashing for a single event', async () => {
        renderInsight({ query: aggregatedBar(), featureFlags: HOG_CHARTS_FLAG })

        await waitFor(() => {
            expect(screen.getByRole('img', { name: /chart with/i })).toBeInTheDocument()
        })
    })

    it('emits one series per breakdown so each bar gets its own color', async () => {
        renderInsight({
            query: aggregatedBar({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        // Five hedgehog breakdowns → five sparse-stacked series sharing five bands.
        await waitFor(() => {
            expect(screen.getByRole('img', { name: /chart with 5 data series/i })).toBeInTheDocument()
        })
    })

    it('opens the persons modal on click without resolving a day', async () => {
        renderInsight({ query: aggregatedBar(), featureFlags: HOG_CHARTS_FLAG })

        await chart.clickAtIndex(0)

        await waitFor(() => {
            expect(personsModal.get()).toBeInTheDocument()
        })
        // Aggregated mode has no DateDisplay in the title.
        expect(personsModal.title()).not.toMatch(/Wednesday/)
    })

    it('fires context.onDataPointClick without a day argument', async () => {
        // Per-band breakdown resolution is covered at the unit-handler level — the
        // hog-charts hover/click helpers don't yet handle horizontal axis-orientation, so
        // integration coverage stays at the single-bar level here.
        const onDataPointClick = jest.fn()
        renderInsight({
            query: aggregatedBar(),
            context: { onDataPointClick },
            featureFlags: HOG_CHARTS_FLAG,
        })

        await chart.clickAtIndex(0)

        await waitFor(() => {
            expect(onDataPointClick).toHaveBeenCalledTimes(1)
        })
        const [seriesArg] = onDataPointClick.mock.calls[0]
        expect(seriesArg.day).toBeUndefined()
    })

    it('renders InsightEmptyState when every aggregated_value is zero', async () => {
        renderInsight({
            query: aggregatedBar({
                series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
        })
    })
})

describe('TrendsBarChart (ActionsUnstackedBar)', () => {
    const groupedBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
        buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsUnstackedBar }, ...extra })

    it('routes grouped bar insights through the hog-charts adapter', async () => {
        renderInsight({ query: groupedBar(), featureFlags: HOG_CHARTS_FLAG })

        await waitFor(() => {
            expect(screen.getByTestId('trend-bar-graph')).toBeInTheDocument()
        })
    })

    it('renders one band per series in grouped layout', async () => {
        renderInsight({
            query: groupedBar({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
        })
    })
})

describe('TrendsBarChart overlays', () => {
    it('renders value labels when showValuesOnSeries is enabled', async () => {
        renderInsight({
            query: buildTrendsQuery({
                trendsFilter: { display: ChartDisplayType.ActionsBar, showValuesOnSeries: true },
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await screen.findByRole('img', { name: /chart with/i })
        await waitFor(() => {
            expect(getHogChart().valueLabels().length).toBeGreaterThan(0)
        })
        const labels = getHogChart()
            .valueLabels()
            .map((l) => l.text)
        // Pageview series peaks at 210 — it should appear among the rendered labels.
        expect(labels).toContain('210')
    })

    it('renders an annotation badge when an annotation exists', async () => {
        renderInsight({
            query: buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsBar } }),
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

        await screen.findByRole('img', { name: /chart with/i })
        await waitFor(() => {
            expect(getHogChart().annotationBadges().length).toBeGreaterThan(0)
        })
    })

    // For ActionsBarValue (horizontal aggregated), axisOrientation='horizontal' flips the
    // line geometry to a vertical stripe at the value-axis x-pixel.
    it.each<{ display: ChartDisplayType; value: number; expectedOrientation: 'horizontal' | 'vertical' }>([
        { display: ChartDisplayType.ActionsBar, value: 150, expectedOrientation: 'horizontal' },
        { display: ChartDisplayType.ActionsBarValue, value: 100, expectedOrientation: 'vertical' },
    ])(
        'renders a goal line with $expectedOrientation orientation for $display',
        async ({ display, value, expectedOrientation }) => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { display, goalLines: [{ label: 'Target', value, displayIfCrossed: true }] },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            await screen.findByRole('img', { name: /chart with/i })
            const lines = getHogChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(['Target'])
            expect(lines[0].orientation).toBe(expectedOrientation)
        }
    )
})
