import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

type ClassifyArgs = {
    model?: string
    messages?: Array<{ role: string; content: string }>
    response_format?: Record<string, unknown>
}

const sanitizeProduct = (raw: string): string => raw.replace(/[^a-z0-9_-]/gi, '').toLowerCase() || 'workflows'

const buildGatewayUrl = (rawBase: string, product: string): string => {
    const base = rawBase.replace(/\/+$/, '')
    return `${base}/${sanitizeProduct(product)}/v1/chat/completions`
}

registerAsyncFunction('postHogLLMClassify', {
    execute: (args, context, result) => {
        const [opts] = args as [ClassifyArgs | undefined]

        const model = opts?.model
        const messages = opts?.messages
        const responseFormat = opts?.response_format

        if (!model || typeof model !== 'string') {
            throw new Error("[HogFunction] - postHogLLMClassify call missing 'model' property")
        }
        if (!Array.isArray(messages) || messages.length === 0) {
            throw new Error("[HogFunction] - postHogLLMClassify call missing 'messages' property")
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
        })
    },

    mock: (args, logs) => {
        const opts = (args[0] ?? {}) as ClassifyArgs
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogLLMClassify' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogLLMClassify(${JSON.stringify(opts, null, 2)})`,
        })

        const isStructured = !!opts.response_format
        const mockContent = isStructured
            ? JSON.stringify({ category: 'mock-category', reasoning: 'mock reasoning' })
            : 'mock free-form classification'

        return {
            status: 200,
            body: {
                choices: [{ message: { content: mockContent } }],
            },
        }
    },
})
