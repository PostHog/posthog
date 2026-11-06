import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EvalSuggestionApi, EvalSuggestionListApi } from '../../generated/api.schemas'
import { traceDrawerLogic } from '../../redesign/trace/traceDrawerLogic'
import { llmProviderKeysLogic } from '../../settings/llmProviderKeysLogic'
import { SUGGESTION_EXAMPLES_LIST, evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'

const SUGGESTIONS_URL = '/api/projects/:team_id/evaluation_suggestions'

function suggestion(overrides: Partial<EvalSuggestionApi> = {}): EvalSuggestionApi {
    return {
        id: 'code-1',
        kind: 'new_hog',
        status: 'proposed',
        template_key: 'unrecovered_errors',
        headline: '1 in 125 traces ends on a failed call',
        outcome: 'Checks every trace for a tool or model call that failed with no recovery.',
        reason: 'A tool call failed and no later attempt succeeded.',
        draft: { evaluation_type: 'hog' },
        filters: [],
        rollout_percentage: 100,
        measured_failure_rate: 0.004,
        sample_size: 250,
        evidence: [
            { trace_id: 'trace-1', reason: 'The turn ended on a timeout' },
            { trace_id: 'trace-2', reason: 'The turn ended on a 429' },
        ],
        estimated_weekly_runs: null,
        estimated_weekly_cost_usd: null,
        judge_model: '',
        created_evaluation: null,
        target_evaluation: null,
        target_evaluation_name: null,
        similar_evaluation: null,
        similar_evaluation_name: null,
        dismiss_reason: null,
        created_at: '2026-11-01T00:00:00Z',
        ...overrides,
    }
}

const CODE_CHECK = suggestion()
const JUDGE = suggestion({
    id: 'judge-1',
    kind: 'new_llm_judge',
    template_key: 'structured_output_gap',
    measured_failure_rate: null,
    sample_size: null,
    estimated_weekly_runs: 124,
    estimated_weekly_cost_usd: 0.01,
})

const LIST: EvalSuggestionListApi = {
    run: {
        id: 'run-1',
        trigger: 'scheduled',
        created_at: '2026-11-01T00:00:00Z',
        completed_at: '2026-11-01T00:05:00Z',
    },
    pending: false,
    results: [CODE_CHECK, JUDGE],
}

function trackingProperties(item: EvalSuggestionApi): Record<string, string> {
    return { suggestion_id: item.id, kind: item.kind, template_key: item.template_key }
}

describe('evaluationSuggestionsLogic', () => {
    let logic: ReturnType<typeof evaluationSuggestionsLogic.build>
    let capture: jest.SpyInstance

    beforeEach(async () => {
        useMocks({ get: { [`${SUGGESTIONS_URL}/`]: LIST } })
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        logic = evaluationSuggestionsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEvalSuggestionsSuccess'])
        // The provider key loads start on mount, and a late one would overwrite the key a test sets up.
        await expectLogic(llmProviderKeysLogic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        capture.mockRestore()
    })

    it('tracks each open suggestion as shown once per page view', async () => {
        await expectLogic(logic, () => logic.actions.loadEvalSuggestions()).toDispatchActions([
            'loadEvalSuggestionsSuccess',
        ])

        expect(capture.mock.calls.filter(([event]) => event === 'llma eval suggestion shown')).toEqual([
            ['llma eval suggestion shown', trackingProperties(CODE_CHECK)],
            ['llma eval suggestion shown', trackingProperties(JUDGE)],
        ])
    })

    it('adds a code check, drops its card and opens the new eval', async () => {
        useMocks({
            post: {
                [`${SUGGESTIONS_URL}/:id/accept/`]: {
                    suggestion: { ...CODE_CHECK, status: 'accepted', created_evaluation: 'eval-1' },
                    evaluation_id: 'eval-1',
                    backfill_id: 'backfill-1',
                    backfill_units: 250,
                },
            },
        })

        await expectLogic(logic, () => logic.actions.acceptSuggestion(CODE_CHECK)).toFinishAllListeners()

        expect(logic.values.inFlight).toBeNull()
        expect(logic.values.suggestionList?.results.map(({ id }) => id)).toEqual([JUDGE.id])
        expect(router.values.location.pathname).toContain(urls.aiObservabilityEvaluation('eval-1'))
        expect(capture).toHaveBeenCalledWith('llma eval suggestion accepted', trackingProperties(CODE_CHECK))
    })

    it.each([
        ['offers the key settings without a working key', null, true],
        ['leaves out the key settings with a working key', { id: 'key-1', provider: 'openai', state: 'ok' }, false],
    ])('keeps the judge confirm open when accept is refused, and %s', async (_, activeProviderKey, needsKey) => {
        const refusal =
            "LLM judges run on your own AI provider API key, and this project doesn't have a working one yet."
        useMocks({
            get: {
                '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                    active_provider_key: activeProviderKey,
                },
                [`${SUGGESTIONS_URL}/:id/accept_estimate/`]: {
                    target: 'trace',
                    units: 50,
                    window_start: '2026-10-31T00:00:00Z',
                    window_end: '2026-11-01T00:00:00Z',
                    judge_model: 'gpt-5-mini',
                    estimated_cost_usd: 0.02,
                },
            },
            post: {
                [`${SUGGESTIONS_URL}/:id/accept/`]: () => [
                    400,
                    { type: 'validation_error', code: 'invalid', detail: refusal, attr: null },
                ],
            },
        })
        await expectLogic(llmProviderKeysLogic, () =>
            llmProviderKeysLogic.actions.loadEvaluationConfig()
        ).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.openJudgeConfirm(JUDGE))
            .toDispatchActions(['loadEvalSuggestionEstimateSuccess'])
            .toMatchValues({ evalSuggestionEstimate: partial({ units: 50, judge_model: 'gpt-5-mini' }) })
        const pathBefore = router.values.location.pathname

        await expectLogic(logic, () => logic.actions.acceptSuggestion(JUDGE)).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            judgeConfirm: JUDGE,
            judgeConfirmError: refusal,
            judgeConfirmNeedsProviderKey: needsKey,
            inFlight: null,
        })
        expect(router.values.location.pathname).toEqual(pathBefore)
        expect(capture).not.toHaveBeenCalledWith('llma eval suggestion accepted', expect.anything())
    })

    it("opens a card's examples in the trace drawer, each labeled with why it is there", () => {
        const flag = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN
        featureFlagLogic.actions.setFeatureFlags([flag], { [flag]: true })
        router.actions.push(urls.aiObservabilityEvaluations())

        logic.actions.openExamples(CODE_CHECK)

        expect(traceDrawerLogic({ listId: SUGGESTION_EXAMPLES_LIST }).values).toMatchObject({
            openTraceId: 'trace-1',
            openLabel: 'The turn ended on a timeout',
            position: { index: 0, total: 2 },
        })
        expect(capture).toHaveBeenCalledWith('llma eval suggestion examples opened', trackingProperties(CODE_CHECK))
    })

    it('dismisses with the chosen reason and drops the card', async () => {
        const dismissBodies: unknown[] = []
        useMocks({
            post: {
                [`${SUGGESTIONS_URL}/:id/dismiss/`]: async ({ request }) => {
                    dismissBodies.push(await request.json())
                    return { ...CODE_CHECK, status: 'dismissed', dismiss_reason: 'too_noisy' }
                },
            },
        })

        await expectLogic(logic, () => logic.actions.dismissSuggestion(CODE_CHECK, 'too_noisy')).toFinishAllListeners()

        expect(dismissBodies).toEqual([{ reason: 'too_noisy' }])
        expect(logic.values.suggestionList?.results.map(({ id }) => id)).toEqual([JUDGE.id])
        expect(capture).toHaveBeenCalledWith('llma eval suggestion dismissed', {
            ...trackingProperties(CODE_CHECK),
            reason: 'too_noisy',
        })
    })
})
