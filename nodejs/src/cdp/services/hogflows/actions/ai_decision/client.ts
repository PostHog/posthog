import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { FetchResponse, internalFetch } from '~/common/utils/request'

import { AiDecisionConfig, isPlainObject } from './config'

export type AiDecisionRequest = {
    teamId: number
    hogFlowId?: string
    invocationId: string
    actionId: string
    config: AiDecisionConfig
    state: Record<string, unknown>
}

export type AiDecisionReply =
    | { status: 'answered'; probabilities: Record<string, number>; model: string }
    | { status: 'failed'; code: string; message: string }
    | { status: 'throttled'; retryAfterSeconds?: number }
    | { status: 'unavailable'; retryAfterSeconds?: number }

export const AI_DECISION_UNAVAILABLE_MESSAGE =
    "The AI service couldn't take the request. Contact support if this keeps happening."
const INVALID_REQUEST_MESSAGE =
    "The AI decision service rejected the step's request. Check the step's question, options, and context, and contact support if this keeps happening."

function retryAfter(headers: Record<string, string>): number | undefined {
    const value = headers['retry-after']?.trim()
    if (!value || !/^\d+$/.test(value)) {
        return undefined
    }
    const seconds = Number(value)
    return Number.isSafeInteger(seconds) ? seconds : undefined
}

function finalReply(body: unknown): AiDecisionReply {
    if (isPlainObject(body)) {
        if (body.status === 'succeeded' && isPlainObject(body.probabilities) && typeof body.model === 'string') {
            return {
                status: 'answered',
                probabilities: body.probabilities as Record<string, number>,
                model: body.model,
            }
        }
        if (
            body.status === 'failed' &&
            isPlainObject(body.error) &&
            typeof body.error.code === 'string' &&
            typeof body.error.message === 'string'
        ) {
            return { status: 'failed', code: body.error.code, message: body.error.message }
        }
    }
    return { status: 'failed', code: 'gateway_unavailable', message: AI_DECISION_UNAVAILABLE_MESSAGE }
}

export class AiDecisionClient {
    constructor(
        private jwt: ScopedServiceJwt,
        private internalApiBaseUrl: string
    ) {}

    get enabled(): boolean {
        return this.jwt.enabled
    }

    async decide(request: AiDecisionRequest): Promise<AiDecisionReply> {
        if (!this.enabled) {
            return { status: 'failed', code: 'gateway_unavailable', message: AI_DECISION_UNAVAILABLE_MESSAGE }
        }
        const token = this.jwt.mint({
            ...(request.hogFlowId && request.hogFlowId !== 'new' ? { hog_flow_id: request.hogFlowId } : {}),
            team_id: request.teamId,
        })
        let response: FetchResponse
        try {
            response = await internalFetch(
                `${this.internalApiBaseUrl}/api/projects/${request.teamId}/workflow_ai_decisions/`,
                {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                    timeoutMs: 15_000,
                    body: JSON.stringify({
                        invocation_id: request.invocationId,
                        action_id: request.actionId,
                        ...request.config,
                        state: request.state,
                    }),
                }
            )
        } catch {
            return { status: 'unavailable' }
        }
        if (response.status === 429) {
            await response.dump().catch(() => {})
            return { status: 'throttled', retryAfterSeconds: retryAfter(response.headers) }
        }
        if (response.status >= 500 && response.status < 600) {
            await response.dump().catch(() => {})
            return { status: 'unavailable', retryAfterSeconds: retryAfter(response.headers) }
        }
        if (response.status !== 200) {
            await response.dump().catch(() => {})
            return { status: 'failed', code: 'invalid_request', message: INVALID_REQUEST_MESSAGE }
        }
        try {
            return finalReply(await response.json())
        } catch {
            return { status: 'failed', code: 'gateway_unavailable', message: AI_DECISION_UNAVAILABLE_MESSAGE }
        }
    }
}
