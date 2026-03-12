import { cleanup, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'

import { initKeaTests } from '../init'
import {
    breakdown,
    buildTrendsQuery,
    compare,
    display,
    expectNoNaN,
    generateData,
    getChart,
    interval,
    renderInsight,
    series,
    waitForChart,
} from './index'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('InsightTestHarness', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [] },
                '/api/environments/:team_id/insights/trend': [],
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders a basic trends line chart with correct data', async () => {
        renderInsight({})

        const chart = await waitForChart(1)
        expect(chart.datasets[0].label).toBe('$pageview')
        expect(chart.datasets[0].data).toEqual(generateData('$pageview'))

        expectNoNaN()
    })

    it('renders multiple series with indexed access', async () => {
        renderInsight({
            query: buildTrendsQuery({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: 'Pageviews' },
                    { kind: NodeKind.EventsNode, event: 'Saved a HedgeHog', name: 'Rescues' },
                ],
            }),
        })

        const chart = await waitForChart(2)
        expect(chart.datasets[0].label).toBe('Pageviews')
        expect(chart.datasets[1].label).toBe('Rescues')
    })

    it('exposes labels and chart type', async () => {
        renderInsight({})

        const chart = await waitForChart(1)
        expect(chart.labels.length).toBeGreaterThan(0)
        expect(chart.type).toBe('line')
    })

    it('exposes y-axis tick formatting', async () => {
        renderInsight({})

        await waitFor(() => {
            const chart = getChart()
            expect(chart.axes.y.tickLabel(500)).toBeTruthy()
            expect(chart.axes.y.display).toBe(true)
        })
    })

    it('does not produce NaN values for sparse series', async () => {
        renderInsight({})

        await waitForChart(1)
        expectNoNaN()
    })

    describe('interactions', () => {
        it('clicking interval dropdown changes the interval', async () => {
            renderInsight({ showFilters: true })
            await waitForChart(1)

            await interval.set('week')
        })

        it('clicking compare dropdown enables comparison', async () => {
            renderInsight({ showFilters: true })
            await waitForChart(1)

            await compare.enable()
        })

        it('clicking display dropdown changes chart type', async () => {
            renderInsight({ showFilters: true })
            await waitForChart(1)

            await display.set('Bar chart')
        })

        it('select event, breakdown by rescue method, assert breakdown values in chart', async () => {
            renderInsight({ showFilters: true })
            await waitForChart(1)

            await series.select(0, 'Saved a HedgeHog')
            await breakdown.set('rescue_method')

            const chart = await waitForChart(5)
            expect(chart.datasets[0].label).toBe('from road')
            expect(chart.datasets[0].data).toEqual(generateData('Saved a HedgeHog::from road'))
            expect(chart.datasets[1].label).toBe('from garden')
            expect(chart.datasets[1].data).toEqual(generateData('Saved a HedgeHog::from garden'))
        })
    })
})
