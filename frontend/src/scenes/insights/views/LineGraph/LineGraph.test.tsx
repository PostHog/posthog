import { cleanup } from '@testing-library/react'

import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import {
    buildTrendsQuery,
    type MockResponse,
    type QueryBody,
    renderInsightPage,
    waitForChart,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

// Current period: Jun 10-14, Previous period: Jun 3-7
// Deliberately different date ranges so we can detect which one is used for x-axis labels
const CURRENT_DAYS = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const PREVIOUS_DAYS = ['2024-06-03', '2024-06-04', '2024-06-05', '2024-06-06', '2024-06-07']

function compareResponse(): TrendsQueryResponse {
    return {
        results: [
            {
                action: { id: '$pageview', type: 'events', name: '$pageview' },
                label: '$pageview',
                count: 100,
                data: [10, 20, 30, 25, 15],
                labels: ['10-Jun-2024', '11-Jun-2024', '12-Jun-2024', '13-Jun-2024', '14-Jun-2024'],
                days: CURRENT_DAYS,
                compare: true,
                compare_label: 'current',
            },
            {
                action: { id: '$pageview', type: 'events', name: '$pageview' },
                label: '$pageview',
                count: 80,
                data: [8, 15, 25, 20, 12],
                labels: ['3-Jun-2024', '4-Jun-2024', '5-Jun-2024', '6-Jun-2024', '7-Jun-2024'],
                days: PREVIOUS_DAYS,
                compare: true,
                compare_label: 'previous',
            },
        ],
    } as TrendsQueryResponse
}

const compareMock: MockResponse = {
    match: (query: QueryBody) => query.kind === NodeKind.TrendsQuery,
    response: compareResponse,
}

describe('LineGraph', () => {
    afterEach(cleanup)

    describe('Compare to previous', () => {
        it('uses current period dates on x-axis for unstacked bar chart with compare', async () => {
            renderInsightPage({
                query: buildTrendsQuery({
                    trendsFilter: { display: ChartDisplayType.ActionsUnstackedBar },
                    compareFilter: { compare: true },
                }),
                mocks: { mockResponses: [compareMock] },
            })

            const chart = await waitForChart()

            // trendsDataLogic sorts "previous" first for unstacked bar charts
            expect(chart.series(0).compareLabel).toBe('previous')

            const firstTickLabel = chart.axes.x.tickLabel(0)
            expect(firstTickLabel).toBe('Jun 10')
        })
    })
})
