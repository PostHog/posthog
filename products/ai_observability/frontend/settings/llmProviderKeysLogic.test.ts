import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    LLMProvider,
    LLMProviderKey,
    getEditKeyFieldError,
    llmProviderKeysLogic,
    normalizeLLMProvider,
    normalizeSystemOneBaseUrlForComparison,
    toLLMProvider,
} from './llmProviderKeysLogic'

function makeKey(provider: LLMProvider, azureEndpoint: string | null = null): LLMProviderKey {
    return {
        id: 'key-1',
        provider,
        name: 'Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-...1234',
        azure_endpoint_display: azureEndpoint,
        api_version_display: null,
        base_url_display: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        last_used_at: null,
    }
}

describe('llmProviderKeysLogic', () => {
    it.each([
        ['google', 'gemini'],
        ['google-ai-studio', 'gemini'],
        ['azure_openai', 'azure_openai'],
        ['azure-openai', 'azure_openai'],
        ['azure openai', 'azure_openai'],
        ['together', 'together_ai'],
        ['together ai', 'together_ai'],
        ['together-ai', 'together_ai'],
        ['mini max', 'minimax'],
        ['mini-max', 'minimax'],
        ['minimax', 'minimax'],
        ['openai-compatible', 'openai_compatible'],
        ['openai compatible', 'openai_compatible'],
        ['openai_compatible', 'openai_compatible'],
        ['openai', 'openai'],
        ['System One', 'system_one'],
        ['system_one', 'system_one'],
    ])('maps %s to %s', (input, expected) => {
        expect(normalizeLLMProvider(input)).toBe(expected)
    })

    it('trims whitespace before matching aliases', () => {
        expect(normalizeLLMProvider('  mini max  ')).toBe('minimax')
    })

    it('returns null for undefined and unknown providers', () => {
        expect(normalizeLLMProvider(undefined)).toBeNull()
        expect(normalizeLLMProvider('unknown-provider')).toBeNull()
    })

    it('recognizes the System One display name in model pickers', () => {
        expect(toLLMProvider('System One')).toBe('system_one')
    })

    it.each([
        ['https://DECISIONS.example.com/v1/', 'https://decisions.example.com/v1'],
        ['https://decisions.example.com:443/v1', 'https://decisions.example.com/v1'],
    ])('treats %s as the same endpoint as %s', (input, expected) => {
        expect(normalizeSystemOneBaseUrlForComparison(input)).toBe(expected)
    })

    it.each([
        ['an Azure endpoint', true, makeKey('azure_openai'), 400, 'azure_endpoint'],
        ['an Azure API version', true, makeKey('azure_openai'), 400, 'api_version'],
        [
            'a Foundry endpoint',
            true,
            makeKey('anthropic', 'https://example.services.ai.azure.com/'),
            400,
            'azure_endpoint',
        ],
        ['an OpenAI-compatible base URL', true, makeKey('openai_compatible'), 400, 'base_url'],
        ['a name', true, makeKey('openai'), 400, 'name'],
        ['a System One base URL', true, makeKey('system_one'), 400, 'base_url'],
        ['a System One model ID', true, makeKey('system_one'), 400, 'system_one_model'],
        ['a System One model ID on a non-System One key', false, makeKey('openai'), 400, 'system_one_model'],
        ['an Azure endpoint on a non-Azure key', false, makeKey('openai'), 400, 'azure_endpoint'],
        ['an Azure endpoint with a server error', false, makeKey('azure_openai'), 500, 'azure_endpoint'],
        ['a 400 without a field', false, makeKey('azure_openai'), 400, null],
    ])('attributes %s to an edit modal input: %s', (_, inline, key, status, attr) => {
        const errorObject = new ApiError(undefined, status, undefined, { attr, detail: 'This field may not be blank.' })
        expect(getEditKeyFieldError(key, errorObject)).toEqual(
            inline ? { field: attr, message: 'This field may not be blank.' } : null
        )
    })

    describe('saving an edited key', () => {
        const azureKey = makeKey('azure_openai', 'https://example.openai.azure.com/')
        let logic: ReturnType<typeof llmProviderKeysLogic.build>
        let patchResponse: [number, Record<string, unknown>]

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [azureKey] },
                    '/api/environments/:teamId/llm_analytics/evaluation_config/': { active_provider_key: null },
                },
                patch: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/:id/': () => patchResponse,
                },
            })
            initKeaTests()
            logic = llmProviderKeysLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            jest.restoreAllMocks()
        })

        it.each([
            [
                'shows a rejected Azure endpoint under its input without a toast',
                'azure_endpoint',
                'This field may not be blank.',
                { field: 'azure_endpoint', message: 'This field may not be blank.' },
                [],
            ],
            [
                'toasts a rejected field that has no input exactly once',
                'provider',
                "A key's provider cannot change. Create a new key instead.",
                null,
                [["Failed to update API key: A key's provider cannot change. Create a new key instead."]],
            ],
        ])('%s', async (_, attr, detail, expectedFieldError, expectedToasts) => {
            patchResponse = [400, { type: 'validation_error', code: 'invalid', detail, attr }]
            const toast = jest.spyOn(lemonToast, 'error').mockReturnValue('')
            logic.actions.setEditingKey(azureKey)

            await expectLogic(logic, () => {
                logic.actions.updateProviderKey({ id: azureKey.id, payload: { azure_endpoint: '' } })
            })
                .toDispatchActions(['updateProviderKeyFailure'])
                .toFinishAllListeners()
            expect(logic.values.keyFieldError).toEqual(expectedFieldError)
            expect(toast.mock.calls).toEqual(expectedToasts)
        })
    })

    describe('creating a key', () => {
        let logic: ReturnType<typeof llmProviderKeysLogic.build>

        afterEach(() => {
            logic.unmount()
            jest.restoreAllMocks()
        })

        it.each([
            [
                'shows a rejected System One model ID under its input without a toast',
                'system_one_model',
                { field: 'system_one_model', message: 'The endpoint returned 404 for this model ID.' },
                [],
            ],
            [
                'toasts a rejected field that the add modal has no inline error for',
                'base_url',
                null,
                [['Failed to create API key: The endpoint returned 404 for this model ID.']],
            ],
        ])('%s', async (_, attr, expectedFieldError, expectedToasts) => {
            useMocks({
                get: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                    '/api/environments/:teamId/llm_analytics/evaluation_config/': { active_provider_key: null },
                },
                post: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/': () => [
                        400,
                        {
                            type: 'validation_error',
                            code: 'invalid',
                            detail: 'The endpoint returned 404 for this model ID.',
                            attr,
                        },
                    ],
                },
            })
            initKeaTests()
            logic = llmProviderKeysLogic()
            logic.mount()
            const toast = jest.spyOn(lemonToast, 'error').mockReturnValue('')

            await expectLogic(logic, () => {
                logic.actions.createProviderKey({
                    payload: {
                        provider: 'system_one',
                        name: 'Custom',
                        api_key: '',
                        base_url: 'https://decisions.example.com/v1',
                        system_one_model: 'example-model',
                    },
                })
            })
                .toDispatchActions(['createProviderKeyFailure'])
                .toFinishAllListeners()
            expect(logic.values.keyFieldError).toEqual(expectedFieldError)
            expect(toast.mock.calls).toEqual(expectedToasts)
        })
    })

    describe('offering back the evaluations a key turned off', () => {
        const key = makeKey('anthropic')
        let logic: ReturnType<typeof llmProviderKeysLogic.build>
        let patched: string[]

        const evaluation = (id: string, enabled: boolean, status_reason: string | null): Record<string, unknown> => ({
            id,
            name: `Evaluation ${id}`,
            model_configuration_id: 'config-1',
            enabled,
            status_reason,
        })

        beforeEach(() => {
            patched = []
            useMocks({
                get: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [key] },
                    '/api/environments/:teamId/llm_analytics/evaluation_config/': { active_provider_key: null },
                    '/api/environments/:teamId/llm_analytics/provider_keys/:id/dependent_configs/': {
                        evaluations: [
                            evaluation('by-key', false, 'provider_key_quota_exceeded'),
                            evaluation('by-person', false, null),
                            evaluation('running', true, null),
                        ],
                        alternative_keys: [],
                        active_key_evaluations: [
                            { ...evaluation('by-active-key', false, 'provider_key_quota_exceeded') },
                        ],
                    },
                },
                post: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/:id/validate/': { ...key, state: 'ok' },
                },
                patch: {
                    '/api/projects/:teamId/evaluations/:id/': ({ params }) => {
                        patched.push(params.id as string)
                        return [200, {}]
                    },
                },
            })
            initKeaTests()
            logic = llmProviderKeysLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('offers only the evaluations a key problem turned off, and turns them back on', async () => {
            await expectLogic(logic, () => logic.actions.validateProviderKey({ id: key.id }))
                .toDispatchActions(['validateProviderKeySuccess', 'loadTurnedOffEvaluationsSuccess'])
                .toFinishAllListeners()
            expect(logic.values.turnedOffEvaluations?.evaluations.map((turnedOff) => turnedOff.id)).toEqual([
                'by-key',
                'by-active-key',
            ])

            await expectLogic(logic, () => logic.actions.turnEvaluationsBackOn())
                .toDispatchActions(['turnEvaluationsBackOnSuccess'])
                .toFinishAllListeners()
            expect(patched.sort()).toEqual(['by-active-key', 'by-key'])
            expect(logic.values.turnedOffEvaluations).toBeNull()
        })
    })
})
