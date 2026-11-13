import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationConditionSet, EvaluationConfig } from '../types'
import { evaluationFixSuggestionLogic } from './evaluationFixSuggestionLogic'

function conditions(product: string): EvaluationConditionSet[] {
    return [
        {
            id: 'scouts',
            rollout_percentage: 100,
            properties: [{ key: 'ai_product', value: [product], operator: 'exact', type: 'event' }],
        },
    ] as EvaluationConditionSet[]
}

const EVALUATION: EvaluationConfig = {
    id: 'eval-1',
    name: 'Scout findings are grounded',
    description: '',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true', bytecode: [] },
    output_type: 'boolean',
    output_config: { allows_na: true },
    conditions: conditions('signals'),
    target: 'trace',
    target_config: {},
    model_configuration: null,
    total_runs: 0,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
}

const FIX: EvalSuggestionApi = {
    id: 'fix-1',
    kind: 'fix_eval',
    status: 'proposed',
    applies: true,
    template_key: '',
    headline: 'Your "Scout findings are grounded" eval stopped running',
    outcome: 'Its filter looks for ai_product = signals, which your traffic stopped sending.',
    reason: '',
    draft: { conditions: conditions('signals_scout') },
    filters: [],
    rollout_percentage: 100,
    measured_failure_rate: null,
    sample_size: null,
    evidence: [],
    estimated_weekly_runs: null,
    estimated_weekly_cost_usd: null,
    judge_model: '',
    created_evaluation: null,
    target_evaluation: 'eval-1',
    target_evaluation_name: 'Scout findings are grounded',
    similar_evaluation: null,
    similar_evaluation_name: null,
    dismiss_reason: null,
    created_at: '2026-11-01T00:00:00Z',
}

describe('evaluationFixSuggestionLogic', () => {
    let savedConditions: EvaluationConditionSet[]

    beforeEach(() => {
        savedConditions = conditions('signals')
        useMocks({
            get: {
                '/api/llm_proxy/models/': [],
                '/api/projects/:team_id/evaluations/:id/': () => [200, { ...EVALUATION, conditions: savedConditions }],
                '/api/projects/:team_id/evaluation_suggestions/:id/': FIX,
            },
            post: {
                '/api/projects/:team_id/evaluation_suggestions/:id/apply_fix/': () => {
                    savedConditions = conditions('signals_scout')
                    return [200, { ...FIX, status: 'accepted' }]
                },
            },
        })
        initKeaTests()
    })

    it('opens on the filter, and reloads the form after applying so saving it again keeps the fix', async () => {
        const evaluationLogic = llmEvaluationLogic({ evaluationId: 'eval-1' })
        evaluationLogic.mount()
        await expectLogic(evaluationLogic).toDispatchActions(['loadEvaluationSuccess'])
        router.actions.push(urls.aiObservabilityEvaluation('eval-1'), { suggestion: 'fix-1' })
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const logic = evaluationFixSuggestionLogic({ suggestionId: 'fix-1', evaluationId: 'eval-1' })
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadSuggestionSuccess'])
            .toMatchValues({ openFix: partial({ id: 'fix-1' }) })
        expect(evaluationLogic.values.formStep).toBe('traffic')

        await expectLogic(logic, () => logic.actions.applyFix()).toFinishAllListeners()
        await expectLogic(evaluationLogic).toDispatchActions(['loadEvaluationSuccess'])

        expect(evaluationLogic.values.evaluation?.conditions).toEqual(conditions('signals_scout'))
        expect(logic.values.openFix).toBeNull()
        expect(router.values.searchParams.suggestion).toBeUndefined()
        expect(capture).toHaveBeenCalledWith('llma eval suggestion accepted', {
            suggestion_id: 'fix-1',
            kind: 'fix_eval',
            template_key: '',
        })
        evaluationLogic.unmount()
    })

    it('keeps edits made while the fix applies, with the new filter in the form', async () => {
        const evaluationLogic = llmEvaluationLogic({ evaluationId: 'eval-1' })
        evaluationLogic.mount()
        await expectLogic(evaluationLogic).toDispatchActions(['loadEvaluationSuccess'])
        const logic = evaluationFixSuggestionLogic({ suggestionId: 'fix-1', evaluationId: 'eval-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSuggestionSuccess'])

        await expectLogic(logic, () => {
            logic.actions.applyFix()
            evaluationLogic.actions.setEvaluationName('Renamed while applying')
        }).toFinishAllListeners()

        expect(evaluationLogic.values.evaluation).toMatchObject({
            name: 'Renamed while applying',
            conditions: conditions('signals_scout'),
        })
        evaluationLogic.unmount()
    })
})
