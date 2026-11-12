import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EvaluationSampleTrafficItemApi, TestHogResultItemApi } from '../generated/api.schemas'
import { evaluationsTestOnSampleCreateBodySampleIdsMax } from '../generated/api.zod'
import { JUDGE_TEST_LIMIT, evaluationPreviewLogic, resultOutcome } from './evaluationPreviewLogic'
import { llmEvaluationLogic } from './llmEvaluationLogic'
import type { EvaluationConfig } from './types'

const props = { evaluationId: 'eval-1' }

const sample = (sampleId: string): EvaluationSampleTrafficItemApi => ({
    sample_id: sampleId,
    sample_type: 'trace',
    trace_id: sampleId,
    timestamp: '2026-11-05T10:00:00Z',
    input_preview: '',
    output_preview: '',
})

const evaluation = {
    id: 'eval-1',
    name: 'Tools',
    description: '',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true' },
    output_type: 'boolean',
    output_config: {},
    conditions: [{ id: 'c1', rollout_percentage: 100, properties: [] }],
    target: 'trace',
    target_config: {},
    model_configuration: null,
    total_runs: 0,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
} as EvaluationConfig

const testResult = {
    sample_id: 'a',
    sample_type: 'trace',
    event_uuid: null,
    trace_id: 'a',
    input_preview: '',
    output_preview: '',
    result: true,
    reasoning: '',
    error: null,
    outcome: 'pass',
}

describe('evaluationPreviewLogic', () => {
    let logic: ReturnType<typeof evaluationPreviewLogic.build>
    let testCalls: string[]
    let testedIds: string[][]
    let inFlight: number
    let mostInFlight: number
    let saved: EvaluationConfig
    let pending: Promise<void> | null
    let failure: [number, Record<string, string>] | null

    beforeEach(() => {
        testCalls = []
        testedIds = []
        inFlight = 0
        mostInFlight = 0
        pending = null
        failure = null
        const respond =
            (endpoint: string) =>
            async ({ request }: { request: Request }) => {
                testCalls.push(endpoint)
                testedIds.push(((await request.json()) as { sample_ids: string[] }).sample_ids)
                mostInFlight = Math.max(mostInFlight, ++inFlight)
                await pending
                inFlight--
                return failure ?? [200, { results: [testResult] }]
            }
        useMocks({
            get: { '/api/projects/:teamId/evaluations/:id/': () => [200, saved] },
            post: {
                '/api/projects/:teamId/evaluations/sample_traffic/': { results: ['a', 'b', 'c', 'd'].map(sample) },
                '/api/projects/:teamId/evaluations/test_hog/': respond('hog'),
                '/api/projects/:teamId/evaluations/test_on_sample/': respond('judge'),
            },
        })
        initKeaTests()
    })

    const mount = (config: EvaluationConfig): void => {
        saved = config
        llmEvaluationLogic(props).mount()
        llmEvaluationLogic(props).actions.loadEvaluationSuccess(config)
        logic = evaluationPreviewLogic(props)
        logic.mount()
    }

    it.each([
        ['a judge result passes on true', 'llm_judge', {}, testResult, 'pass'],
        ['a judge detector fails on true', 'llm_judge', { true_is_failure: true }, testResult, 'fail'],
        ['a Hog result keeps the outcome the server gave it', 'hog', { true_is_failure: true }, testResult, 'pass'],
        [
            'a judge keeps a not-applicable answer',
            'llm_judge',
            {},
            { ...testResult, result: null, outcome: 'na' },
            'na',
        ],
    ])('%s', (_name, evaluationType, outputConfig, result, outcome) => {
        expect(
            resultOutcome(
                result as TestHogResultItemApi,
                {
                    ...evaluation,
                    evaluation_type: evaluationType,
                    output_config: outputConfig,
                } as EvaluationConfig
            )
        ).toBe(outcome)
    })

    it('tests no more runs with a judge than the server accepts', () => {
        expect(JUDGE_TEST_LIMIT).toBe(evaluationsTestOnSampleCreateBodySampleIdsMax)
    })

    it('tests hog code on the traffic without a click, and again after each edit', async () => {
        mount(evaluation)
        await expectLogic(logic).toFinishAllListeners()
        expect(testCalls).toEqual(['hog'])
        expect(testedIds).toEqual([['a', 'b', 'c', 'd']])
        expect(Object.keys(logic.values.testResults ?? {})).toEqual(['a'])

        llmEvaluationLogic(props).actions.setHogSource('return false')
        await expectLogic(logic).toFinishAllListeners()

        expect(testCalls).toEqual(['hog', 'hog'])
    })

    it('holds the next automatic test until the one in flight returns', async () => {
        mount({ ...evaluation, target: 'generation' } as EvaluationConfig)
        await expectLogic(logic).toFinishAllListeners()
        let release = (): void => {}
        pending = new Promise((resolve) => {
            release = resolve
        })

        llmEvaluationLogic(props).actions.setHogSource('return false')
        while (testCalls.length < 2) {
            await new Promise((resolve) => setTimeout(resolve, 10))
        }
        llmEvaluationLogic(props).actions.setHogSource('return 1 == 1')
        await new Promise((resolve) => setTimeout(resolve, 700))
        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(testCalls).toEqual(['hog', 'hog', 'hog'])
        expect(mostInFlight).toBe(1)
    })

    it('tests a judge only on a click, and clears its results once the prompt changes', async () => {
        mount({
            ...evaluation,
            evaluation_type: 'llm_judge',
            evaluation_config: { prompt: 'Is it helpful?' },
            model_configuration: { provider: 'openai', model: 'gpt-4.1-mini', provider_key_id: 'key-1' },
        } as EvaluationConfig)
        await expectLogic(logic).toFinishAllListeners()
        expect(testCalls).toEqual([])

        await expectLogic(logic, () => logic.actions.testRows({ auto: false })).toFinishAllListeners()
        expect(Object.keys(logic.values.testResults ?? {})).toEqual(['a'])
        // Each run is a paid call, and the server rejects a fourth id.
        expect(testedIds).toEqual([['a', 'b', 'c']])

        llmEvaluationLogic(props).actions.setEvaluationPrompt('Is it accurate?')

        expect(logic.values.testResults).toBeNull()
        expect(testCalls).toEqual(['judge'])
    })

    it.each([
        [
            'code that does not compile',
            [400, { error: 'Compilation error on line 2: unexpected token', code: 'hog_compile_error' }],
            'Compilation error on line 2: unexpected token',
            'Compilation error on line 2: unexpected token',
        ],
        ['a busy server', [500, { detail: 'Too many queries' }], 'Too many queries', null],
    ] as [string, [number, Record<string, string>], string, string | null][])(
        'reports %s',
        async (_name, response, testError, codeError) => {
            failure = response
            mount(evaluation)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.testError).toBe(testError)
            expect(logic.values.codeError).toBe(codeError)
        }
    )

    it.each([
        ['result', null, true],
        ['failure', [500, { detail: 'Failed' }], false],
    ] as [string, [number, Record<string, string>] | null, boolean][])(
        'drops a judge %s that arrives after the prompt changed',
        async (_outcome, response, saysDiscarded) => {
            failure = response
            mount({
                ...evaluation,
                evaluation_type: 'llm_judge',
                evaluation_config: { prompt: 'Is it helpful?' },
                model_configuration: { provider: 'openai', model: 'gpt-4.1-mini', provider_key_id: 'key-1' },
            } as EvaluationConfig)
            await expectLogic(logic).toFinishAllListeners()
            let release = (): void => {}
            pending = new Promise((resolve) => {
                release = resolve
            })

            logic.actions.testRows({ auto: false })
            llmEvaluationLogic(props).actions.setEvaluationPrompt('Is it accurate?')
            // The paid call is still running, so the button must not offer a second one yet.
            expect(logic.values.testResultsLoading).toBe(true)
            release()
            await expectLogic(logic).toFinishAllListeners()

            expect(testCalls).toEqual(['judge'])
            expect(logic.values.testResults).toBeNull()
            expect(logic.values.testError).toBeNull()
            expect(logic.values.testDiscarded).toBe(saysDiscarded)
        }
    )
})
