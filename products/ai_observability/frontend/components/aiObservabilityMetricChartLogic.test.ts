import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

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
            logic.actions.openBucketTrace({ label: '2026-11-10T18:28:00Z' })
        ).toFinishAllListeners()

        expect(router.values.searchParams.trace).toBe(openTrace)
    })

    it('opens the trace page from the Users tab, which has no drawer', async () => {
        router.actions.push(urls.aiObservabilityUsers(), { date_from: '-1h' })
        jest.mocked(performQuery).mockResolvedValue({ results: [['trace-1', '2026-11-10T18:28:02Z']] } as any)
        const logic = aiObservabilityMetricChartLogic({ metric: 'users' })
        logic.mount()

        await expectLogic(logic, () =>
            logic.actions.openBucketTrace({ label: '2026-11-10T18:28:00Z' })
        ).toFinishAllListeners()

        expect(router.values.location.pathname).toContain(urls.aiObservabilityTrace('trace-1'))
    })

    it.each([
        ['hides support traces on the Traces tab', urls.aiObservabilityTraces(), undefined, true],
        ['keeps them on the Users tab, as its table does', urls.aiObservabilityUsers(), 'users', false],
    ] as const)('%s', (_name, url, metric, hidden) => {
        router.actions.push(url, { date_from: '-1h' })
        const logic = aiObservabilityMetricChartLogic({ metric })
        logic.mount()

        expect(logic.values.filters.properties?.some((p) => String(p.key).includes('ai_support_impersonated'))).toBe(
            hidden
        )
    })

    it.each([
        ['ends at the next bar', '2026-11-10T14:00:00Z', '2026-11-10T14:00:00Z'],
        ["keeps the chart's own end for the last bar", null, '2026-11-10'],
    ])('zooming %s', (_name, nextLabel, dateTo) => {
        router.actions.push(urls.aiObservabilityTraces(), { date_from: '2026-11-10', date_to: '2026-11-10' })
        const logic = aiObservabilityMetricChartLogic({})
        logic.mount()

        logic.actions.zoomTo('2026-11-10T13:00:00Z', nextLabel)

        expect(aiObservabilitySharedLogic.values.dateFilter).toEqual({ dateFrom: '2026-11-10T13:00:00Z', dateTo })
    })
})
