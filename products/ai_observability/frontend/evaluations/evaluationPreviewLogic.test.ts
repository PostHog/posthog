import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EvaluationSampleTrafficItemApi, TestHogResultItemApi } from '../generated/api.schemas'
import { evaluationPreviewLogic, resultPasses } from './evaluationPreviewLogic'
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
}

describe('evaluationPreviewLogic', () => {
    let logic: ReturnType<typeof evaluationPreviewLogic.build>
    let testCalls: string[]
    let saved: EvaluationConfig
    let pending: Promise<void> | null

    beforeEach(() => {
        testCalls = []
        pending = null
        const respond = (endpoint: string) => async () => {
            testCalls.push(endpoint)
            await pending
            return [200, { results: [testResult] }]
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
        ['a plain evaluation passes on true', {}, true],
        ['a detector fails on true, matching the polarity switch', { true_is_failure: true }, false],
    ])('%s', (_name, outputConfig, passes) => {
        expect(
            resultPasses({ ...testResult, result: true } as TestHogResultItemApi, {
                ...evaluation,
                output_config: outputConfig,
            })
        ).toBe(passes)
    })

    it('tests hog code on the traffic without a click, and again after each edit', async () => {
        mount(evaluation)
        await expectLogic(logic).toFinishAllListeners()
        expect(testCalls).toEqual(['hog'])
        expect(Object.keys(logic.values.testResults ?? {})).toEqual(['a'])

        llmEvaluationLogic(props).actions.setHogSource('return false')
        await expectLogic(logic).toFinishAllListeners()

        expect(testCalls).toEqual(['hog', 'hog'])
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

        llmEvaluationLogic(props).actions.setEvaluationPrompt('Is it accurate?')

        expect(logic.values.testResults).toBeNull()
        expect(testCalls).toEqual(['judge'])
    })

    it('drops a judge result that arrives after the prompt changed', async () => {
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
        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(testCalls).toEqual(['judge'])
        expect(logic.values.testResults).toBeNull()
    })
})
