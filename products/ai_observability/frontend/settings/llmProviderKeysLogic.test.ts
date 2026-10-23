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
        ['a System One base URL', false, makeKey('system_one'), 400, 'base_url'],
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
            expect(logic.values.editKeyFieldError).toEqual(expectedFieldError)
            expect(toast.mock.calls).toEqual(expectedToasts)
        })
    })
})
