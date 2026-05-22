import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { ensureJsdom, waitForHogChartTooltip } from 'lib/hog-charts/testing'
import { FUNNEL_CONVERSION_SERIES_LABEL } from 'scenes/funnels/viz/shared/funnelSeriesMeta'

import { buildFunnelsQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'

ensureJsdom()

afterEach(() => {
    personsModal.cleanupAll()
    cleanup()
})

const HOG_CHARTS_FUNNEL_FLAG = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_FUNNEL]: true }

describe('FunnelLineChart', () => {
    describe('series rendering', () => {
        it('renders a single conversion series with percentage values in the tooltip', async () => {
            renderInsight({ query: buildFunnelsQuery(), featureFlags: HOG_CHARTS_FUNNEL_FLAG })

            const tooltip = await chart.hoverTooltip(2)

            expect(getHogChart().seriesCount).toBe(1)
            expect(tooltip.element.textContent).toContain(FUNNEL_CONVERSION_SERIES_LABEL)
            expect(tooltip.element.textContent).toContain('40%')
        })

        it('renders a series per breakdown variant', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FUNNEL_FLAG,
            })

            await waitFor(() => {
                expect(getHogChart().seriesCount).toBe(2)
            })
        })

        it('shows the breakdown label on each tooltip row when broken down', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FUNNEL_FLAG,
            })

            await chart.clickAtIndex(2)
            const tooltip = await waitForHogChartTooltip()
            expect(tooltip.textContent).toContain('Spike')
            expect(tooltip.textContent).toContain('Bramble')
        })
    })

    describe('click → persons modal', () => {
        it('opens the persons modal with the day-scoped actors for a single-series chart', async () => {
            renderInsight({ query: buildFunnelsQuery(), featureFlags: HOG_CHARTS_FUNNEL_FLAG })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['funnel-wed-a@example.com', 'funnel-wed-b@example.com'])
            })
            expect(personsModal.title()).toMatch(/12 Jun/)
        })

        it('opens the persons modal scoped to the clicked breakdown row', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
                featureFlags: HOG_CHARTS_FUNNEL_FLAG,
            })

            await chart.clickAtIndex(2)
            await chart.clickTooltipRow('Spike')

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['funnel-spike@example.com'])
            })
        })
    })

    describe('value labels overlay', () => {
        it('renders percentage value labels when showValuesOnSeries is enabled', async () => {
            renderInsight({
                query: buildFunnelsQuery({ funnelsFilter: { showValuesOnSeries: true } }),
                featureFlags: HOG_CHARTS_FUNNEL_FLAG,
            })

            await screen.findByRole('img', { name: /chart with/i })
            await waitFor(() => {
                const texts = getHogChart()
                    .valueLabels()
                    .map((l) => l.text)
                // default fixture data [10, 25, 40, 60, 35] rendered as percentages
                expect([...texts].sort()).toEqual(['10%', '25%', '35%', '40%', '60%'])
            })
        })
    })

    describe('goal lines', () => {
        it('renders configured goal lines on the chart', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    funnelsFilter: { goalLines: [{ label: 'Target', value: 30, displayIfCrossed: true }] },
                }),
                featureFlags: HOG_CHARTS_FUNNEL_FLAG,
            })

            await screen.findByRole('img', { name: /chart with/i })
            const lines = getHogChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(['Target'])
        })
    })

    describe('trend lines overlay', () => {
        it('adds a trend-line series when showTrendLines is enabled', async () => {
            renderInsight({
                query: buildFunnelsQuery({ funnelsFilter: { showTrendLines: true } }),
                featureFlags: HOG_CHARTS_FUNNEL_FLAG,
            })

            // main series + trend-line series = 2
            await waitFor(() => {
                expect(getHogChart().seriesCount).toBe(2)
            })
        })
    })
})
