import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationsLogic } from './evaluations/llmEvaluationsLogic'
import { HogEvaluation } from './evaluations/types'
import { generationEvaluationRunsLogic } from './generationEvaluationRunsLogic'

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')

    return {
        __esModule: true,
        ...actual,
        default: {
            ...actual.default,
            queryHogQL: jest.fn().mockResolvedValue({ results: [] }),
        },
    }
})

const evaluation = (id: string, target: 'generation' | 'trace'): HogEvaluation => ({
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
    conditions: [{ id: `condition-${id}`, rollout_percentage: 100, properties: [] }],
    target,
    target_config: {},
    model_configuration: null,
    total_runs: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
})

describe('generationEvaluationRunsLogic', () => {
    let evaluationsLogic: ReturnType<typeof llmEvaluationsLogic.build>
    let logic: ReturnType<typeof generationEvaluationRunsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/': { results: [] },
                '/api/projects/:teamId/evaluation_directories/': [],
            },
        })
        initKeaTests()
        evaluationsLogic = llmEvaluationsLogic()
        evaluationsLogic.mount()
        logic = generationEvaluationRunsLogic({ traceId: 'trace-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        evaluationsLogic.unmount()
    })

    // The manual run endpoint only accepts generation-target evaluations, and the picked id outlives
    // the list it came from. Reading the selection back through the runnable list is what stops a
    // retargeted or deleted evaluation from being dispatched into a 400.
    it('drops a selection that is no longer runnable on a single generation', () => {
        evaluationsLogic.actions.loadEvaluationsSuccess([
            evaluation('eval-1', 'generation'),
            { ...evaluation('eval-2', 'generation'), deleted: true },
            evaluation('eval-3', 'trace'),
        ])
        logic.actions.setSelectedEvaluationId('eval-1')

        expect(logic.values.runnableEvaluations.map((e) => e.id)).toEqual(['eval-1'])
        expect(logic.values.selectedEvaluation?.id).toBe('eval-1')

        evaluationsLogic.actions.loadEvaluationsSuccess([evaluation('eval-1', 'trace')])

        expect(logic.values.runnableEvaluations).toEqual([])
        expect(logic.values.selectedEvaluation).toBeNull()
        expect(logic.values.selectedEvaluationId).toBe('eval-1')
    })
})
