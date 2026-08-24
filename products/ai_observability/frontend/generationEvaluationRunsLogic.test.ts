import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationsLogic } from './evaluations/llmEvaluationsLogic'
import { generationEvaluationRunsLogic } from './generationEvaluationRunsLogic'

const evaluation = (id: string, target: 'generation' | 'trace'): Record<string, unknown> => ({
    id,
    name: `Evaluation ${id}`,
    description: '',
    directory_id: null,
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true' },
    output_type: 'boolean',
    output_config: {},
    conditions: [],
    target,
    target_config: {},
    model_configuration: null,
    created_at: '2026-08-06T00:00:00Z',
    updated_at: '2026-08-06T00:00:00Z',
})

describe('generationEvaluationRunsLogic', () => {
    let logic: ReturnType<typeof generationEvaluationRunsLogic.build>
    let evaluationsLogic: ReturnType<typeof llmEvaluationsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:teamId/evaluations/': {
                    results: [evaluation('eval-generation', 'generation'), evaluation('eval-trace', 'trace')],
                },
                '/api/projects/:teamId/evaluation_directories/': [],
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': { active_provider_key: null },
            },
            post: {
                '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        evaluationsLogic = llmEvaluationsLogic()
        evaluationsLogic.mount()
        logic = generationEvaluationRunsLogic({ traceId: 'trace-1' })
        logic.mount()
        await expectLogic(evaluationsLogic).toDispatchActions(['loadEvaluationsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        evaluationsLogic?.unmount()
    })

    // A manual run only works on a generation, so a trace-target evaluation must never be
    // offered or dispatched — the backend rejects it, which is what put this in error tracking.
    it('offers only generation-target evaluations and drops a selection that is not one', () => {
        expect(logic.values.runnableEvaluations.map((e) => e.id)).toEqual(['eval-generation'])

        logic.actions.setSelectedEvaluationId('eval-generation')
        expect(logic.values.selectedRunnableEvaluationId).toBe('eval-generation')

        logic.actions.setSelectedEvaluationId('eval-trace')
        expect(logic.values.selectedRunnableEvaluationId).toBeNull()
    })
})
