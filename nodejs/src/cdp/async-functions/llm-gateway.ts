import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { AsyncFunctionContext, registerAsyncFunction } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'

type ChatCompletionArgs = {
    model?: string
    messages?: Array<{ role: string; content: string }>
    response_format?: Record<string, unknown>
}

// Template-id allowlist: this async function injects PostHog's internal LLM gateway service key
// into outbound requests, so it MUST NOT be callable from arbitrary user-authored destination
// Hog functions. Any caller whose hogFunction.template_id is not on this list is rejected, even
// if Hog code references postHogLLMChatCompletion by name. template_id is set server-side from
// the HogFunctionType record — users cannot spoof it from Hog code.
const ALLOWED_LLM_TEMPLATE_IDS: ReadonlySet<string> = new Set([
    'template-posthog-llm-classify',
    'template-posthog-llm-summarize',
    'template-posthog-llm-extract',
])

const FN_NAME = 'postHogLLMChatCompletion'

const buildGatewayUrl = (rawBase: string): string => {
    const base = rawBase.replace(/\/+$/, '')
    return `${base}/workflows/v1/chat/completions`
}

const queueChatCompletionFetch = (
    opts: ChatCompletionArgs | undefined,
    context: AsyncFunctionContext,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
): void => {
    const callerTemplateId = context.invocation.hogFunction.template_id ?? ''
    if (!ALLOWED_LLM_TEMPLATE_IDS.has(callerTemplateId)) {
        throw new Error(
            `[HogFunction] - ${FN_NAME} is restricted to PostHog-built LLM templates; caller template_id='${callerTemplateId}' is not allowed`
        )
    }

    const model = opts?.model
    const messages = opts?.messages
    const responseFormat = opts?.response_format

    if (!model || typeof model !== 'string') {
        throw new Error(`[HogFunction] - ${FN_NAME} call missing 'model' property`)
    }
    if (!Array.isArray(messages) || messages.length === 0) {
        throw new Error(`[HogFunction] - ${FN_NAME} call missing 'messages' property`)
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
        url: buildGatewayUrl(context.llmGatewayUrl),
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

// Derives a structurally valid mock response from the caller's response_format. Returning a
// concrete object keyed off the requested schema means a single mock works for classify
// ({category, reasoning}), summarize ({title, description}), extract ({...user-defined fields}),
// and any future LLM-action template without a per-caller fixture.
const deriveMockContent = (opts: ChatCompletionArgs): string => {
    const schema = (opts.response_format as any)?.json_schema?.schema
    const props = schema?.properties as Record<string, any> | undefined
    if (!props) {
        return 'mock free-form response'
    }
    const mock: Record<string, unknown> = {}
    for (const [key, propRaw] of Object.entries(props)) {
        const prop = propRaw as any
        if (Array.isArray(prop.enum) && prop.enum.length > 0) {
            mock[key] = prop.enum[0]
        } else if (prop.type === 'number' || prop.type === 'integer') {
            mock[key] = 0
        } else if (prop.type === 'boolean') {
            mock[key] = false
        } else if (prop.type === 'array') {
            mock[key] = []
        } else {
            mock[key] = `mock ${key}`
        }
    }
    return JSON.stringify(mock)
}

registerAsyncFunction(FN_NAME, {
    execute: (args, context, result) => {
        const [opts] = args as [ChatCompletionArgs | undefined]
        queueChatCompletionFetch(opts, context, result)
    },

    mock: (args, logs) => {
        const opts = (args[0] ?? {}) as ChatCompletionArgs
        const mockContent = deriveMockContent(opts)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function '${FN_NAME}' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `${FN_NAME}(${JSON.stringify(opts, null, 2)})`,
        })
        return {
            status: 200,
            body: {
                choices: [{ message: { content: mockContent } }],
            },
        }
    },
})

// Exported for tests; the runtime gate uses this set directly.
export const __TESTING_ALLOWED_LLM_TEMPLATE_IDS = ALLOWED_LLM_TEMPLATE_IDS
