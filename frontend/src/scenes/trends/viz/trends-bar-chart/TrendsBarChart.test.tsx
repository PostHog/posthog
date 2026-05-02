import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom } from 'lib/hog-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, personsModal, renderInsight } from '~/test/insight-testing'
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
