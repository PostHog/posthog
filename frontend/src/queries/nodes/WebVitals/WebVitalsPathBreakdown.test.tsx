import { render, waitFor } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { NodeKind, WebVitalsMetric, WebVitalsPathBreakdownQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { initKeaTests } from '~/test/init'
import { PropertyMathType } from '~/types'

import { WebVitalsPathBreakdown } from './WebVitalsPathBreakdown'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const performQueryMock = performQuery as jest.Mock

const context: QueryContext = {
    insightProps: { dashboardItemId: 'new-web-vitals-path-breakdown', dataNodeCollectionId: 'web-analytics' },
}

function queryFor(metric: WebVitalsMetric): WebVitalsPathBreakdownQuery {
    return {
        kind: NodeKind.WebVitalsPathBreakdownQuery,
        dateRange: { date_from: '-7d' },
        filterTestAccounts: false,
        properties: [],
        percentile: PropertyMathType.P90,
        metric,
        thresholds: [100, 200],
    }
}

describe('WebVitalsPathBreakdown', () => {
    beforeEach(() => {
        initKeaTests()
        performQueryMock.mockReset()
        performQueryMock.mockImplementation(() =>
            Promise.resolve({ results: [{ good: [], needs_improvements: [], poor: [] }] })
        )
    })

    // Each metric tab percentiles an unmaterialized property over the same events, so a tab the
    // person already opened must not pay for that scan a second time.
    it('queries each metric once while the rest of the query is unchanged', async () => {
        const { rerender } = render(<WebVitalsPathBreakdown query={queryFor('FCP')} context={context} />)
        await waitFor(() => expect(performQueryMock).toHaveBeenCalledTimes(1))

        rerender(<WebVitalsPathBreakdown query={queryFor('LCP')} context={context} />)
        await waitFor(() => expect(performQueryMock).toHaveBeenCalledTimes(2))

        rerender(<WebVitalsPathBreakdown query={queryFor('FCP')} context={context} />)
        rerender(<WebVitalsPathBreakdown query={queryFor('LCP')} context={context} />)

        expect(performQueryMock).toHaveBeenCalledTimes(2)
    })

    it('drops the held metrics when the filters change', async () => {
        const withHost = (query: WebVitalsPathBreakdownQuery): WebVitalsPathBreakdownQuery => ({
            ...query,
            dateRange: { date_from: '-30d' },
        })

        const { rerender } = render(<WebVitalsPathBreakdown query={queryFor('FCP')} context={context} />)
        await waitFor(() => expect(performQueryMock).toHaveBeenCalledTimes(1))

        rerender(<WebVitalsPathBreakdown query={withHost(queryFor('FCP'))} context={context} />)
        await waitFor(() => expect(performQueryMock).toHaveBeenCalledTimes(2))

        rerender(<WebVitalsPathBreakdown query={queryFor('FCP')} context={context} />)
        await waitFor(() => expect(performQueryMock).toHaveBeenCalledTimes(3))
    })
})
