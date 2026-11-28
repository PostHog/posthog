jest.unmock('lib/utils/concurrencyController')

import { cleanup, render, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { MetricsQueryRenderer } from '~/queries/Query/queryNodeRenderers'
import { initKeaTests } from '~/test/init'

import { MetricsTableDrilldownModal } from './MetricsTableDrilldownModal'

describe('MetricsTableDrilldownModal', () => {
    beforeAll(() => MetricsQueryRenderer.preload())
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('loads six charts with bounded concurrency and retains them when reopened', async () => {
        const pending: (() => void)[] = []
        let blockResponses = true
        let queryCalls = 0
        let inFlight = 0
        let maxInFlight = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async () => {
                    queryCalls++
                    maxInFlight = Math.max(maxInFlight, ++inFlight)
                    if (blockResponses) {
                        await new Promise<void>((resolve) => pending.push(resolve))
                    }
                    inFlight--
                    return [200, { results: [] }]
                },
            },
        })
        const modal = (
            <MetricsTableDrilldownModal
                config={{
                    groupBy: 'service.name',
                    dateRange: { date_from: '-1h' },
                    orderByColumn: 0,
                    orderDirection: 'DESC',
                    limit: 50,
                    columns: Array.from({ length: 6 }, (_, index) => ({
                        label: `Metric ${index}`,
                        metricName: `metric_${index}`,
                        aggregation: 'sum',
                    })),
                }}
                names={['example-service']}
                labelValues={[['example-service']]}
                onClose={() => {}}
            />
        )
        const { rerender, getAllByText } = render(modal)
        try {
            await waitFor(() => expect(queryCalls).toBe(3))
            for (let expectedCalls = 4; expectedCalls <= 6; expectedCalls++) {
                pending.shift()!()
                await waitFor(() => expect(queryCalls).toBe(expectedCalls))
            }
        } finally {
            blockResponses = false
            pending.forEach((resolve) => resolve())
        }
        await waitFor(() => expect(document.querySelector('.Spinner')).toBeNull())
        expect(maxInFlight).toBe(3)
        expect(queryCalls).toBe(6)

        rerender(<MetricsTableDrilldownModal {...modal.props} names={[]} labelValues={[]} />)
        rerender(modal)
        await waitFor(() => expect(getAllByText('No data for this metric in the selected range.')).toHaveLength(6))
        expect(queryCalls).toBe(6)
    })
})
