import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { aiObservabilityMetricChartLogic } from './aiObservabilityMetricChartLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

describe('aiObservabilityMetricChartLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN]: true,
        })
        router.actions.push(urls.aiObservabilityTraces(), { date_from: '-1h' })
    })

    it.each([
        ['opens the drawer when the minute holds one trace', [['trace-1', '2026-11-10T18:28:02Z']], 'trace-1'],
        [
            'leaves the list alone when the minute holds several traces',
            [
                ['trace-1', '2026-11-10T18:28:02Z'],
                ['trace-2', '2026-11-10T18:28:30Z'],
            ],
            undefined,
        ],
    ])('%s', async (_name, results, openTrace) => {
        jest.mocked(performQuery).mockResolvedValue({ results } as any)
        const logic = aiObservabilityMetricChartLogic({})
        logic.mount()

        await expectLogic(logic, () => logic.actions.openBucketTrace('2026-11-10 18:28:00')).toFinishAllListeners()

        expect(router.values.searchParams.trace).toBe(openTrace)
    })
})
