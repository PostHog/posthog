import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { parseJSON } from '~/common/utils/json-parse'
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
// Django's gateway call can wait 5 s to connect and 5 s more to read. The worker waits past both, because a
// worker that gives up first asks again for a decision the gateway may still bill.
const DECIDE_TIMEOUT_MS = 15_000

function retryAfter(headers: Record<string, string>): number | undefined {
    const value = headers['retry-after']?.trim()
    if (!value || !/^\d+$/.test(value)) {
        return undefined
    }
    const seconds = Number(value)
    return Number.isSafeInteger(seconds) ? seconds : undefined
}

const GATEWAY_UNAVAILABLE: AiDecisionReply = {
    status: 'failed',
    code: 'gateway_unavailable',
    message: AI_DECISION_UNAVAILABLE_MESSAGE,
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
    return GATEWAY_UNAVAILABLE
}

async function readFinalReply(response: FetchResponse): Promise<AiDecisionReply> {
    let text: string
    try {
        text = await response.text()
    } catch {
        // The connection broke after the status line, so the decision may not have finished: ask again later.
        return { status: 'unavailable' }
    }
    try {
        return finalReply(parseJSON(text))
    } catch {
        return GATEWAY_UNAVAILABLE
    }
}

async function replyFor(response: FetchResponse): Promise<AiDecisionReply> {
    if (response.status === 200) {
        return readFinalReply(response)
    }
    await response.dump().catch(() => {})
    if (response.status === 429) {
        return { status: 'throttled', retryAfterSeconds: retryAfter(response.headers) }
    }
    if (response.status >= 500) {
        return { status: 'unavailable', retryAfterSeconds: retryAfter(response.headers) }
    }
    return { status: 'failed', code: 'invalid_request', message: INVALID_REQUEST_MESSAGE }
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
        let response: FetchResponse
        try {
            response = await internalFetch(
                `${this.internalApiBaseUrl}/api/projects/${request.teamId}/workflow_ai_decisions/`,
                {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${this.tokenFor(request)}`, 'Content-Type': 'application/json' },
                    timeoutMs: DECIDE_TIMEOUT_MS,
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
        return replyFor(response)
    }

    private tokenFor(request: AiDecisionRequest): string {
        const hogFlowClaim = request.hogFlowId && request.hogFlowId !== 'new' ? { hog_flow_id: request.hogFlowId } : {}
        return this.jwt.mint({ ...hogFlowClaim, team_id: request.teamId })
    }
}
