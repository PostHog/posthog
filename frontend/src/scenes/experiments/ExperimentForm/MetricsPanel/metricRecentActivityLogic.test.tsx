import { act, cleanup, render } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { MetricRecentActivity } from './MetricRecentActivity'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const meanMetric = (overrides: Partial<ExperimentMetric> = {}, properties: object[] = []): ExperimentMetric =>
    ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.MEAN,
        source: { kind: NodeKind.EventsNode, event: 'purchase', properties },
        ...overrides,
    }) as ExperimentMetric

describe('MetricRecentActivity', () => {
    let resolvers: (() => void)[]

    beforeEach(() => {
        initKeaTests()
        resolvers = []
        jest.mocked(performQuery).mockReset()
        jest.mocked(performQuery).mockImplementation(
            () => new Promise((resolve) => resolvers.push(() => resolve({ results: [] })))
        )
    })

    afterEach(cleanup)

    it.each([
        [
            'inline and shared metric with one uuid',
            meanMetric({ uuid: 'same-uuid' }),
            meanMetric({ uuid: 'same-uuid', sharedMetricId: 7, isSharedMetric: true }, [{ key: 'country' }]),
        ],
        [
            'one shared metric listed twice with different content',
            meanMetric({ uuid: 'same-uuid', sharedMetricId: 7, isSharedMetric: true }),
            meanMetric({ uuid: 'same-uuid', sharedMetricId: 7, isSharedMetric: true }, [{ key: 'country' }]),
        ],
    ])('fetches the count once per card for %s', async (_name, first, second) => {
        render(
            <>
                <MetricRecentActivity metric={first} filterTestAccounts={true} />
                <MetricRecentActivity metric={second} filterTestAccounts={true} />
            </>
        )
        expect(performQuery).toHaveBeenCalledTimes(2)

        await act(async () => {
            resolvers.splice(0).forEach((resolve) => resolve())
        })

        expect(performQuery).toHaveBeenCalledTimes(2)
    })
})
