import { parseJSON } from '~/common/utils/json-parse'

import { LlmStepCompletion, LlmStepRequest } from './llm-step.types'

// Raised by the gateway client so the executor can decide whether to retry. `retriable` maps 429 /
// 5xx / network errors to true and 4xx request errors to false.
export class LlmGatewayError extends Error {
    constructor(
        message: string,
        public retriable: boolean,
        public status?: number
    ) {
        super(message)
        this.name = 'LlmGatewayError'
    }
}

// The seam the executor calls. Kept narrow so tests inject a fake and the executor never talks to a
// real provider. The real implementation routes through the PostHog LLM gateway, which owns
// provider credentials, failover, admission-path spend control, and $ai_generation settlement.
export interface LlmGatewayClient {
    complete(request: LlmStepRequest, opts: { idempotencyKey: string }): Promise<LlmStepCompletion>
}

export interface FetchLlmGatewayClientConfig {
    // Base URL of the gateway, e.g. https://.../llm-gateway. The client posts to `${baseUrl}/v1/chat/completions`.
    baseUrl: string
    // Resolves the bearer token for a team (a project API key in the real gateway). MVP: injected.
    resolveAuthToken: (teamId: number) => Promise<string> | string
    // Per-request timeout in ms. Reasoning models need this well above the default; the parked job's
    // max_wait_duration is the outer backstop.
    requestTimeoutMs: number
    fetchImpl?: typeof fetch
}

// Minimal OpenAI-chat-shape client. The gateway is a true-proxy per shape; the MVP speaks the
// OpenAI chat shape only. `response_format: json_schema` responses are parsed into `parsed`.
export class FetchLlmGatewayClient implements LlmGatewayClient {
    private fetchImpl: typeof fetch

    constructor(private config: FetchLlmGatewayClientConfig) {
        this.fetchImpl = config.fetchImpl ?? fetch
    }

    public async complete(request: LlmStepRequest, opts: { idempotencyKey: string }): Promise<LlmStepCompletion> {
        const token = await this.config.resolveAuthToken(request.teamId)
        const body: Record<string, unknown> = {
            model: request.model,
            messages: request.messages.map((m) => ({ role: m.role, content: m.content })),
        }
        if (request.temperature !== undefined) {
            body.temperature = request.temperature
        }
        if (request.maxTokens !== undefined) {
            body.max_tokens = request.maxTokens
        }
        if (request.topP !== undefined) {
            body.top_p = request.topP
        }
        // Provider-specific; forwarded only when set so default calls stay unchanged. The gateway
        // (litellm) maps/ignores these per provider.
        if (request.reasoningEffort !== undefined) {
            body.reasoning_effort = request.reasoningEffort
        }
        if (request.thinking) {
            body.thinking = request.thinking
        }
        if (request.tools) {
            body.tools = request.tools
        }
        if (request.responseFormat === 'json_schema' && request.jsonSchema) {
            body.response_format = { type: 'json_schema', json_schema: request.jsonSchema }
        }

        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), this.config.requestTimeoutMs)
        let response: Response
        try {
            response = await this.fetchImpl(`${this.config.baseUrl}/v1/chat/completions`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
                    // The gateway dedupes replays at its boundary; the key is (jobId, actionId, nonce).
                    'Idempotency-Key': opts.idempotencyKey,
                    // Links the generation back to the workflow run in $ai_generation / LLM analytics.
                    'X-PostHog-Trace-Id': request.jobId,
                },
                body: JSON.stringify(body),
                signal: controller.signal,
            })
        } catch (err) {
            // Aborts and network failures are retriable - nothing was committed on our side.
            throw new LlmGatewayError(`LLM gateway request failed: ${String(err)}`, true)
        } finally {
            clearTimeout(timer)
        }

        if (!response.ok) {
            const text = await response.text().catch(() => '')
            // 429 (pool/budget) and 5xx (provider/gateway) are retriable; other 4xx are not.
            const retriable = response.status === 429 || response.status >= 500
            throw new LlmGatewayError(
                `LLM gateway returned ${response.status}: ${text.slice(0, 500)}`,
                retriable,
                response.status
            )
        }

        const payload = (await response.json()) as any
        const text: string = payload?.choices?.[0]?.message?.content ?? ''
        const completion: LlmStepCompletion = {
            text,
            model: payload?.model,
            usage: payload?.usage
                ? { inputTokens: payload.usage.prompt_tokens, outputTokens: payload.usage.completion_tokens }
                : undefined,
        }
        if (request.responseFormat === 'json_schema') {
            completion.parsed = safeParse(text)
        }
        return completion
    }
}

function safeParse(text: string): unknown {
    try {
        return parseJSON(text)
    } catch {
        return undefined
    }
}
