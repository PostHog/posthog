import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

type ChatCompletionArgs = {
    model?: string
    messages?: Array<{ role: string; content: string }>
    response_format?: Record<string, unknown>
}

const sanitizeProduct = (raw: string): string => raw.replace(/[^a-z0-9_-]/gi, '').toLowerCase() || 'workflows'

const buildGatewayUrl = (rawBase: string, product: string): string => {
    const base = rawBase.replace(/\/+$/, '')
    return `${base}/${sanitizeProduct(product)}/v1/chat/completions`
}

// Shared between postHogLLMClassify and postHogLLMSummarize. The async functions are intentionally
// thin — they validate, resolve gateway URL/auth from server-side config, and dispatch a fetch
// through cyclotron. The only thing that differs between callers is the Hog-side name (which
// becomes part of the error message) and the mock content shape for tests.
const queueChatCompletionFetch = (
    fnName: string,
    opts: ChatCompletionArgs | undefined,
    context: any,
    result: any
): void => {
    const model = opts?.model
    const messages = opts?.messages
    const responseFormat = opts?.response_format

    if (!model || typeof model !== 'string') {
        throw new Error(`[HogFunction] - ${fnName} call missing 'model' property`)
    }
    if (!Array.isArray(messages) || messages.length === 0) {
        throw new Error(`[HogFunction] - ${fnName} call missing 'messages' property`)
    }

    if (!context.llmGatewayUrl) {
        throw new Error('[HogFunction] - PostHog LLM gateway URL is not configured (LLM_GATEWAY_URL)')
    }
    if (!context.llmGatewayApiKey) {
        throw new Error('[HogFunction] - PostHog LLM gateway API key is not configured (LLM_GATEWAY_API_KEY)')
    }

    const body: Record<string, unknown> = { model, messages }
    if (responseFormat) {
        body.response_format = responseFormat
    }
    // Implicit per-end-user accounting in the gateway — pull from the trigger event so users
    // never have to bind {event.distinct_id} themselves on a built-in node.
    const distinctId = context.globals?.event?.distinct_id
    if (distinctId) {
        body.user = distinctId
    }

    result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
        type: 'fetch',
        url: buildGatewayUrl(context.llmGatewayUrl, 'workflows'),
        method: 'POST',
        body: JSON.stringify(body),
        headers: {
            Authorization: `Bearer ${context.llmGatewayApiKey}`,
            'Content-Type': 'application/json',
        },
        // LLM responses regularly exceed the 3s EXTERNAL_REQUEST_TIMEOUT_MS default
        // (gpt-5-mini with reasoning routinely takes 4-8s). Without this override the
        // fetch aborts mid-completion and the Hog VM sees status 500 / body undefined.
        timeout_ms: 120_000,
    })
}

const buildMockResponse = (fnName: string, opts: ChatCompletionArgs, mockContent: string, logs: any[]) => {
    logs.push({
        level: 'info',
        timestamp: DateTime.now(),
        message: `Async function '${fnName}' was mocked with arguments:`,
    })
    logs.push({
        level: 'info',
        timestamp: DateTime.now(),
        message: `${fnName}(${JSON.stringify(opts, null, 2)})`,
    })

    return {
        status: 200,
        body: {
            choices: [{ message: { content: mockContent } }],
        },
    }
}

registerAsyncFunction('postHogLLMClassify', {
    execute: (args, context, result) => {
        const [opts] = args as [ChatCompletionArgs | undefined]
        queueChatCompletionFetch('postHogLLMClassify', opts, context, result)
    },

    mock: (args, logs) => {
        const opts = (args[0] ?? {}) as ChatCompletionArgs
        const isStructured = !!opts.response_format
        const mockContent = isStructured
            ? JSON.stringify({ category: 'mock-category', reasoning: 'mock reasoning' })
            : 'mock free-form classification'
        return buildMockResponse('postHogLLMClassify', opts, mockContent, logs)
    },
})

registerAsyncFunction('postHogLLMSummarize', {
    execute: (args, context, result) => {
        const [opts] = args as [ChatCompletionArgs | undefined]
        queueChatCompletionFetch('postHogLLMSummarize', opts, context, result)
    },

    mock: (args, logs) => {
        const opts = (args[0] ?? {}) as ChatCompletionArgs
        // Summarize is always structured — the template enforces the { title, description } schema.
        const mockContent = JSON.stringify({
            title: 'mock title',
            description: 'mock description',
        })
        return buildMockResponse('postHogLLMSummarize', opts, mockContent, logs)
    },
})
