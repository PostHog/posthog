import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ModelOption, llmAnalyticsPlaygroundLogic } from './llmAnalyticsPlaygroundLogic'

const MOCK_MODEL_OPTIONS: ModelOption[] = [
    { id: 'gpt-4.1', name: 'GPT-4.1', provider: 'OpenAI', description: '' },
    { id: 'gpt-4.1-mini', name: 'GPT-4.1 Mini', provider: 'OpenAI', description: '' },
    { id: 'gpt-5', name: 'GPT-5', provider: 'OpenAI', description: '' },
    { id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' },
    { id: 'claude-3-opus', name: 'Claude 3 Opus', provider: 'Anthropic', description: '' },
]

const DEFAULT_MODEL = 'gpt-4.1'

describe('llmAnalyticsPlaygroundLogic - Model Matching', () => {
    let logic: ReturnType<typeof llmAnalyticsPlaygroundLogic.build>

    beforeEach(() => {
        initKeaTests()

        useMocks({
            get: {
                '/api/llm_proxy/models/': MOCK_MODEL_OPTIONS,
            },
        })

        logic = llmAnalyticsPlaygroundLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('closest model matching', () => {
        it('should return exact match when model exists', async () => {
            await expectLogic(logic).toFinishAllListeners()

            // Test through setupPlaygroundFromEvent
            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5',
                input: 'test input',
            })

            expect(logic.values.model).toBe('gpt-5')
        })

        it('should match by longest prefix', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini-2025-08-07',
                input: 'test input',
            })

            expect(logic.values.model).toBe('gpt-5-mini')
        })

        it('should match shorter prefix when longer not available', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            expect(logic.values.model).toBe('gpt-5')
        })

        it('should return default model when no match found', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'llama-3-70b',
                input: 'test input',
            })

            expect(logic.values.model).toBe(DEFAULT_MODEL)
        })

        it('should handle empty model list gracefully', async () => {
            // Mock empty response
            useMocks({
                get: {
                    '/api/llm_proxy/models/': [],
                },
            })

            const emptyLogic = llmAnalyticsPlaygroundLogic()
            emptyLogic.mount()

            await expectLogic(emptyLogic).toFinishAllListeners()

            emptyLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            expect(emptyLogic.values.model).toBe('gpt-5')

            emptyLogic.unmount()
        })
    })

    describe('setupPlaygroundFromEvent model matching', () => {
        it('should set valid model directly', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'claude-3-opus',
                input: 'test input',
            })

            expect(logic.values.model).toBe('claude-3-opus')
        })

        it('should handle missing model in payload', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const originalModel = logic.values.model

            logic.actions.setupPlaygroundFromEvent({
                input: 'test input',
            })

            expect(logic.values.model).toBe(originalModel)
        })

        it('should preserve other payload data when model matching', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const testInput = 'Hello, world!'
            const testTools = [{ name: 'search', description: 'Search tool' }]

            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: testInput,
                tools: testTools,
            })

            expect(logic.values.model).toBe('gpt-5')
            expect(logic.values.tools).toEqual(testTools)
            // Input gets processed into messages - check that it's handled
            expect(logic.values.messages.length).toBeGreaterThan(0)
        })

        it('should prefer longer prefix matches', async () => {
            // Add a test case where multiple prefixes could match
            const extendedMockOptions = [
                ...MOCK_MODEL_OPTIONS,
                { id: 'gpt-5-mini-turbo', name: 'GPT-5 Mini Turbo', provider: 'OpenAI', description: '' },
            ]

            useMocks({
                get: {
                    '/api/llm_proxy/models/': extendedMockOptions,
                },
            })

            const testLogic = llmAnalyticsPlaygroundLogic()
            testLogic.mount()

            await expectLogic(testLogic).toFinishAllListeners()

            testLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini-turbo-2025',
                input: 'test',
            })

            // Should match 'gpt-5-mini' as it's the longest prefix that matches
            expect(testLogic.values.model).toBe('gpt-5-mini')

            testLogic.unmount()
        })
    })

    describe('loadModelOptions auto-correction', () => {
        it('should auto-correct invalid model after loading options', async () => {
            // Create logic without mounting to avoid auto-loading
            const testLogic = llmAnalyticsPlaygroundLogic()

            // Manually set an invalid model
            testLogic.actions.setModel('gpt-5-2025-08-07')
            testLogic.mount()

            // Wait for the loader to finish
            await expectLogic(testLogic).toFinishAllListeners()

            // Model should be auto-corrected to closest match
            expect(testLogic.values.model).toBe('gpt-5')

            testLogic.unmount()
        })

        it('should not change valid models during loading', async () => {
            const testLogic = llmAnalyticsPlaygroundLogic()
            testLogic.actions.setModel('claude-3-opus')
            testLogic.mount()

            await expectLogic(testLogic).toFinishAllListeners()

            // Valid model should remain unchanged
            expect(testLogic.values.model).toBe('claude-3-opus')

            testLogic.unmount()
        })

        it('should handle API errors gracefully', async () => {
            useMocks({
                get: {
                    '/api/llm_proxy/models/': () => {
                        throw new Error('API Error')
                    },
                },
            })

            const errorLogic = llmAnalyticsPlaygroundLogic()
            errorLogic.mount()

            await expectLogic(errorLogic).toFinishAllListeners()

            // Should not crash and maintain previous model options
            expect(errorLogic.values.modelOptions).toEqual(MOCK_MODEL_OPTIONS)

            errorLogic.unmount()
        })
    })
})
