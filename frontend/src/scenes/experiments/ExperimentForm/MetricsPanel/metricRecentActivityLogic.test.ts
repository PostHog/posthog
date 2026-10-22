import { expectLogic } from 'kea-test-utils'

import { performQuery } from '~/queries/query'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricRecentActivityLogic } from './metricRecentActivityLogic'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn().mockResolvedValue({ results: [] }),
}))

const meanMetric = (event: string, overrides: Partial<ExperimentMetric> = {}): ExperimentMetric =>
    ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.MEAN,
        source: { kind: NodeKind.EventsNode, event },
        ...overrides,
    }) as ExperimentMetric

describe('metricRecentActivityLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(performQuery).mockClear()
    })

    it('does not refetch when an inline and a shared metric share a uuid', async () => {
        const inlineProps = { metric: meanMetric('purchase', { uuid: 'same-uuid' }), filterTestAccounts: true }
        const sharedProps = {
            metric: meanMetric('signup', { uuid: 'same-uuid', sharedMetricId: 7, isSharedMetric: true }),
            filterTestAccounts: true,
        }

        const inlineLogic = metricRecentActivityLogic(inlineProps)
        const sharedLogic = metricRecentActivityLogic(sharedProps)
        inlineLogic.mount()
        sharedLogic.mount()

        // each card builds its logic again on every render
        metricRecentActivityLogic(inlineProps)
        metricRecentActivityLogic(sharedProps)

        await expectLogic(inlineLogic).toFinishAllListeners()
        await expectLogic(sharedLogic).toFinishAllListeners()

        expect(performQuery).toHaveBeenCalledTimes(2)
    })
})
