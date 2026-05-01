import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom } from 'lib/hog-charts/test-helpers'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, legend, personsModal, renderInsight } from '~/test/insight-testing'
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

describe('TrendsBarChart', () => {
    describe('ActionsBar (vertical stacked bars)', () => {
        const trendsBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
            buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsBar }, ...extra })

        it('renders with one series for a single event', async () => {
            renderInsight({ query: trendsBar(), featureFlags: HOG_CHARTS_FLAG })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 1 data series/i })).toBeInTheDocument()
            })
        })

        it('renders one series per breakdown value', async () => {
            renderInsight({
                query: trendsBar({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FLAG,
            })

            // Five hedgehogs in the canned breakdown fixture.
            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 5 data series/i })).toBeInTheDocument()
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

        it('fires context.onDataPointClick instead of opening the modal when provided', async () => {
            const onDataPointClick = jest.fn()
            renderInsight({
                query: trendsBar(),
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

        it('drops a hidden series from the chart', async () => {
            renderInsight({
                query: trendsBar({
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

            await legend.toggle('Napped')

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 1 data series/i })).toBeInTheDocument()
            })
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
    })
})
