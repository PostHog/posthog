import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
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

        await expectLogic(logic, () =>
            logic.actions.openBucketTrace({ label: '2026-11-10 18:28:00' })
        ).toFinishAllListeners()

        expect(router.values.searchParams.trace).toBe(openTrace)
    })

    it('opens the trace page from the Users tab, which has no drawer', async () => {
        router.actions.push(urls.aiObservabilityUsers(), { date_from: '-1h' })
        jest.mocked(performQuery).mockResolvedValue({ results: [['trace-1', '2026-11-10T18:28:02Z']] } as any)
        const logic = aiObservabilityMetricChartLogic({ metric: 'users' })
        logic.mount()

        await expectLogic(logic, () =>
            logic.actions.openBucketTrace({ label: '2026-11-10 18:28:00' })
        ).toFinishAllListeners()

        expect(router.values.location.pathname).toContain(urls.aiObservabilityTrace('trace-1'))
    })

    it.each([
        ['matches a property filter on any event of a trace', urls.aiObservabilityTraces(), undefined, true],
        ['matches each generation on the Users tab', urls.aiObservabilityUsers(), 'users', false],
    ] as const)('%s', (_name, url, metric, wholeTraces) => {
        router.actions.push(url, { date_from: '-1h' })
        const logic = aiObservabilityMetricChartLogic({ metric })
        logic.mount()
        aiObservabilitySharedLogic.actions.setPropertyFilters([
            {
                key: '$ai_trace_name',
                value: 'checkout',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ])

        expect(logic.values.query.query.includes('properties.$ai_trace_id IN (SELECT')).toBe(wholeTraces)
    })
})
