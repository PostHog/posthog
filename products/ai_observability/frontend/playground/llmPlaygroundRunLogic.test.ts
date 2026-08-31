import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import {
    appendToolCallChunk,
    describeError,
    escapeMarkdownInline,
    llmPlaygroundRunLogic,
    mergeUsage,
} from './llmPlaygroundRunLogic'

function setPlaygroundAccessLevel(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: { llm_playground: level },
    } as typeof window.POSTHOG_APP_CONTEXT
}

describe('llmPlaygroundRunLogic', () => {
    beforeEach(() => {
        initKeaTests()
        // initKeaTests() leaves resource_access_control unset, which the playground gate reads as "no access"
        setPlaygroundAccessLevel(AccessControlLevel.Editor)
        useMocks({
            get: {
                '/api/llm_proxy/models/': [
                    { id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' },
                ],
                '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                },
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: [],
                },
            },
        })
    })

    it('aggregates tool call chunks by id and trailing argument chunks', () => {
        const initial = appendToolCallChunk([], {
            id: 'call_1',
            function: { name: 'get_weather', arguments: '{"city":"' },
        })
        const withContinuation = appendToolCallChunk(initial, {
            id: 'call_1',
            function: { arguments: 'Nicosia"}' },
        })
        const withTrailingChunk = appendToolCallChunk(withContinuation, {
            function: { arguments: '\n{"unit":"celsius"}' },
        })

        expect(withTrailingChunk).toEqual([
            { id: 'call_1', name: 'get_weather', arguments: '{"city":"Nicosia"}\n{"unit":"celsius"}' },
        ])
    })

    it('merges usage chunks without dropping previous non-zero values', () => {
        const merged = mergeUsage(
            { prompt_tokens: 120, completion_tokens: null, total_tokens: null },
            { prompt_tokens: 0, completion_tokens: 56, total_tokens: 176 }
        )

        expect(merged).toEqual({
            prompt_tokens: 120,
            completion_tokens: 56,
            total_tokens: 176,
            cache_read_tokens: null,
            cache_write_tokens: null,
        })
    })

    it('sends sampling settings in completion request payload', async () => {
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
            options.onMessage?.({ data: JSON.stringify({ type: 'text', text: 'ok' }) })
            options.onMessage?.({
                data: JSON.stringify({ type: 'usage', prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 }),
            })
        })

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundPromptsLogic.actions.setTemperature(0.4)
        llmPlaygroundPromptsLogic.actions.setTopP(0.9)
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        expect(streamSpy).toHaveBeenCalledTimes(1)
        expect(streamSpy.mock.calls[0][1]?.data).toMatchObject({
            temperature: 0.4,
            top_p: 0.9,
        })

        logic.unmount()
        streamSpy.mockRestore()
    })

    it('does not run a completion without editor access to the playground and explains why', async () => {
        // Both message textareas submit on Cmd+Enter, bypassing the Run button's disabledReason,
        // so the gate has to hold in the logic itself.
        setPlaygroundAccessLevel(AccessControlLevel.Viewer)
        const streamSpy = jest.spyOn(api, 'stream')
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        expect(streamSpy).not.toHaveBeenCalled()
        expect(toastSpy).toHaveBeenCalledWith(
            "You don't have sufficient permissions for this LLM playground. Your access level (viewer) doesn't meet the required level (editor)."
        )
        await expectLogic(logic).toMatchValues({ submitting: false })

        logic.unmount()
        streamSpy.mockRestore()
        toastSpy.mockRestore()
    })

    it('surfaces backend error message and captures exception when stream fails with ApiError', async () => {
        const apiError = new ApiError('fallback message', 400, undefined, {
            error: 'Thinking is not supported for this model',
        })
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
            options.onError?.(apiError)
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        expect(items[0].response).toContain('**Error:** Thinking is not supported for this model')
        expect(items[0].response).not.toContain('Stream Connection Error')
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            apiError,
            expect.objectContaining({ tag: 'llma-playground-prompt-run', status: 400 })
        )

        logic.unmount()
        streamSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('labels non-ApiError stream failures as connection errors and captures them', async () => {
        const connectionError = new Error('network down')
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
            options.onError?.(connectionError)
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        expect(items[0].response).toContain('**Stream Connection Error:** network down')
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            connectionError,
            expect.objectContaining({ tag: 'llma-playground-prompt-run', status: undefined })
        )

        logic.unmount()
        streamSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('captures exceptions thrown before the stream opens', async () => {
        const thrownError = new ApiError('fallback message', 400, undefined, {
            error: 'Invalid provider key configuration',
        })
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async () => {
            throw thrownError
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        expect(items[0].response).toContain('**Error:** Invalid provider key configuration')
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            thrownError,
            expect.objectContaining({ tag: 'llma-playground-prompt-submit', status: 400 })
        )

        logic.unmount()
        streamSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('names the model when it is not one of the available models', async () => {
        // The model can arrive without passing through the picker — from a trace, or a saved
        // prompt written when the key set still offered it.
        const streamSpy = jest.spyOn(api, 'stream')
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('claude-3-sonnet-20240229')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        // The toast is plain text; the card is markdown, so the model id reaches it escaped.
        expect(toastSpy).toHaveBeenCalledWith(
            "Model 'claude-3-sonnet-20240229' is not one of your available models. Pick a different model and try again."
        )
        expect(items[0].response).toContain(
            "**Error:** Model 'claude\\-3\\-sonnet\\-20240229' is not one of your available models."
        )
        expect(streamSpy).not.toHaveBeenCalled()

        logic.unmount()
        streamSpy.mockRestore()
        toastSpy.mockRestore()
    })

    describe('describeError', () => {
        it('prefers structured backend error string over detail and message', () => {
            const err = new ApiError('fallback', 400, undefined, { error: 'backend says no' })
            expect(describeError(err, 'fallback2')).toEqual({ message: 'backend says no', status: 400 })
        })

        it('ignores non-string data.error payloads and falls back to detail', () => {
            const err = new ApiError('fallback', 400, undefined, {
                error: { field: ['is required'] },
                detail: 'validation failed',
            })
            expect(describeError(err, 'fallback2')).toEqual({ message: 'validation failed', status: 400 })
        })

        it('uses err.message for plain Error instances without a status', () => {
            expect(describeError(new Error('boom'), 'fallback')).toEqual({ message: 'boom' })
        })

        it('returns the fallback for non-Error values', () => {
            expect(describeError('nope', 'fallback')).toEqual({ message: 'fallback' })
        })
    })

    describe('escapeMarkdownInline', () => {
        // A model id can reach the result card straight from an ingested `$ai_model` property,
        // and that card renders markdown with images enabled.
        it('defuses image syntax so an ingested model id cannot issue a request', () => {
            expect(escapeMarkdownInline('![x](https://example.com/pixel)')).toBe(
                '\\!\\[x\\]\\(https\\:\\/\\/example\\.com\\/pixel\\)'
            )
        })

        it('leaves an ordinary model id alone apart from its punctuation', () => {
            expect(escapeMarkdownInline('gpt-4-turbo')).toBe('gpt\\-4\\-turbo')
        })
    })
})
