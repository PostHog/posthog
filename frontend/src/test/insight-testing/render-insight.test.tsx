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
    getChart,
    interval,
    renderInsight,
    series,
    trendsSeries,
    waitForChart,
} from './index'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('renderInsight', () => {
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

    it('renders scoreboard pageviews', async () => {
        renderInsight({})

        const chart = await waitForChart(1)
        expect(chart.series('$pageview').data).toEqual(trendsSeries.pageviews.data)
        expectNoNaN()
    })

    it('renders pageviews and naps side by side', async () => {
        renderInsight({
            query: buildTrendsQuery({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
            }),
        })

        const chart = await waitForChart(2)
        expect(chart.series('$pageview').data).toEqual(trendsSeries.pageviews.data)
        expect(chart.series('Napped').data).toEqual(trendsSeries.napped.data)
        expect(chart.seriesNames).toEqual(['$pageview', 'Napped'])
    })

    it('exposes labels and chart type', async () => {
        renderInsight({})

        const chart = await waitForChart(1)
        expect(chart.labels).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])
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

    it('does not produce NaN values', async () => {
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

        it('breaking down naps by hedgehog shows Spike naps most on Thursdays', async () => {
            renderInsight({ showFilters: true })
            await waitForChart(1)

            await series.select('Napped')
            await breakdown.set('hedgehog')

            const chart = await waitForChart(5)
            expect(chart.seriesNames).toEqual(['Spike', 'Bramble', 'Thistle', 'Conker', 'Prickles'])

            expect(chart.value('Spike', 'Thu')).toBe(4)
            expect(chart.series('Bramble').data).toEqual([0, 0, 1, 1, 0])
        })
    })
})
