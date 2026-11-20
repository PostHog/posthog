import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { registerAsyncFunction } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createAddLogFunction } from '../utils'
import { fetchErrorDetail, getNextRetryTime, isTimeoutError } from '../utils/cdp-fetch'
import { createInvocationResult } from '../utils/invocation-utils'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'

let classifyJwt: ScopedServiceJwt | undefined
const getClassifyJwt = (): ScopedServiceJwt =>
    (classifyJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_CLASSIFY,
        defaultConfig.WORKFLOW_CLASSIFY_JWT_SECRET
    ))

// Django gives the gateway 5 seconds (TIMEOUT_SECONDS in workflow_classifications.py) and returns a 503
// on a gateway timeout, which the classify queue retries. The worker budget must be longer than that plus
// Django's own work. That 5 seconds limits each network operation, not the whole call, so Django can still
// overrun this budget. The worker does not retry its own timeout, because the gateway may still be answering
// the first request and a retry would pay for the same classification again.
const CLASSIFY_TIMEOUT_MS = 7000

// Django answers 503 when the model is busy or unreachable, and a proxy can answer 429 for it.
const BUSY_STATUSES = [429, 503]

// Match the limits of the classification endpoint (the request serializer in workflow_classifications.py),
// so a mocked test run fails on the same inputs as a live run.
const MAX_QUESTION_LENGTH = 2000
const MAX_CATEGORIES = 16
const MAX_CATEGORY_NAME_LENGTH = 100
const MAX_DESCRIPTION_LENGTH = 500
// Counted on the JSON text, like MAX_CONTEXT_CHARS in workflow_classifications.py.
const MAX_CONTEXT_CHARS = 65_536
const MAX_CONTEXT_DEPTH = 100

const nestingExceeds = (value: unknown, limit: number): boolean => {
    const pending: [unknown, number][] = [[value, 1]]
    while (pending.length > 0) {
        const [item, depth] = pending.pop()!
        if (item === null || typeof item !== 'object') {
            continue
        }
        if (depth > limit) {
            return true
        }
        for (const child of Object.values(item)) {
            pending.push([child, depth + 1])
        }
    }
    return false
}

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parseClassifyPayload = (args: any[]): Record<string, unknown> => {
    const [payload] = args as [Record<string, unknown> | undefined]
    if (typeof payload?.question !== 'string' || !payload.question.trim()) {
        throw new Error('Enter a question')
    }
    if ([...payload.question.trim()].length > MAX_QUESTION_LENGTH) {
        throw new Error(`Keep the question to ${MAX_QUESTION_LENGTH} characters or fewer`)
    }
    const categories = payload.categories
    if (!categories || typeof categories !== 'object' || Object.keys(categories).length < 2) {
        throw new Error('Enter at least two categories')
    }
    if (Object.keys(categories).length > MAX_CATEGORIES) {
        throw new Error(`Enter at most ${MAX_CATEGORIES} categories`)
    }
    if (Object.keys(categories).some((name) => !name.trim())) {
        throw new Error('Give every category a name')
    }
    if (Object.keys(categories).some((name) => [...name].length > MAX_CATEGORY_NAME_LENGTH)) {
        throw new Error(`Keep category names to ${MAX_CATEGORY_NAME_LENGTH} characters or fewer`)
    }
    if (
        Object.values(categories).some(
            (description) => typeof description === 'string' && [...description.trim()].length > MAX_DESCRIPTION_LENGTH
        )
    ) {
        throw new Error(`Keep each category description to ${MAX_DESCRIPTION_LENGTH} characters or fewer`)
    }
    if (nestingExceeds(payload.context, MAX_CONTEXT_DEPTH)) {
        throw new Error(`Keep the context to ${MAX_CONTEXT_DEPTH} levels of nesting or fewer`)
    }
    if ([...(JSON.stringify(payload.context) ?? '')].length > MAX_CONTEXT_CHARS) {
        throw new Error(`Keep the context to ${MAX_CONTEXT_CHARS} characters of JSON or fewer`)
    }
    return payload
}

registerAsyncFunction('postHogClassify', {
    execute: (args, context, result) => {
        const payload = parseClassifyPayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Classify with AI only runs inside a workflow')
        }

        result.invocation.queueParameters = { type: 'classify', hogFlowId: hogFlow.id, payload }
    },
    mock: (args, logs) => {
        const payload = parseClassifyPayload(args)
        const categories = Object.keys(payload.categories as Record<string, unknown>)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Classify with AI was mocked. The first category was returned without asking the model.',
        })
        return {
            status: 200,
            body: {
                category: categories[0],
                confidence: 1,
                probabilities: Object.fromEntries(categories.map((name, i) => [name, i === 0 ? 1 : 0])),
            },
        }
    },
})

const DAILY_COUNT_TTL_SECONDS = 2 * 24 * 60 * 60
const DAILY_COUNT_DEADLINE_MS = 500

/** Counts each team's classifications per UTC day, so one team cannot spend the whole model budget. */
export class ClassifyDailyCap {
    constructor(
        private valkey: RedisV2,
        readonly dailyCap: number
    ) {}

    /** Counts one classification and says whether it fits. A slow or failing Valkey lets it through: the queue's limiter still bounds the rate. */
    async countAndCheck(teamId: number): Promise<boolean> {
        const day = new Date(Date.now()).toISOString().slice(0, 10)
        const key = `@posthog/classify-day/{${teamId}}/${day}`
        try {
            const count = await this.valkey.useClient(
                { name: 'classify-daily-cap', failOpen: true, deadlineMs: DAILY_COUNT_DEADLINE_MS },
                async (client) => {
                    const [[, counted]] = (await client
                        .multi()
                        .incr(key)
                        .expire(key, DAILY_COUNT_TTL_SECONDS)
                        .exec()) ?? [[null, 0]]
                    return Number(counted)
                }
            )
            return count === null || count <= this.dailyCap
        } catch {
            return true
        }
    }
}

export interface ClassifyRetryPolicy {
    maxAttempts: number
    backoffBaseMs: number
    backoffMaxMs: number
}

type DjangoAnswer = { status: number; body: unknown } | { error: Error }

const askDjango = async (
    invocation: CyclotronJobInvocationHogFunction,
    internalApiBaseUrl: string,
    params: { hogFlowId: string; payload: Record<string, unknown> }
): Promise<DjangoAnswer> => {
    const token = getClassifyJwt().mint({ hog_flow_id: params.hogFlowId, team_id: invocation.teamId })
    try {
        const response = await internalFetch(
            `${internalApiBaseUrl}/api/projects/${invocation.teamId}/workflow_classifications/`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                body: JSON.stringify(params.payload),
                timeoutMs: CLASSIFY_TIMEOUT_MS,
            }
        )
        const text = await response.text()
        let body: unknown = text
        try {
            body = text ? parseJSON(text) : undefined
        } catch {
            // A body that is not JSON goes to the step as text.
        }
        return { status: response.status, body }
    } catch (error) {
        return { error: error as Error }
    }
}

const isRetriable = (answer: DjangoAnswer): boolean =>
    'error' in answer ? !isTimeoutError(answer.error) : BUSY_STATUSES.includes(answer.status)

/**
 * Makes the one call to the classification endpoint that a dequeue of the classify queue pays for. A busy answer
 * puts the job back on its queue instead of retrying here, so the queue's rate limit counts every call. Any other
 * answer goes onto the VM stack as `{status, body}`, which the template reads.
 */
export async function classifyOnce(
    invocation: CyclotronJobInvocationHogFunction,
    internalApiBaseUrl: string,
    retryPolicy: ClassifyRetryPolicy,
    dailyCap: ClassifyDailyCap | null
): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
    const params = invocation.queueParameters
    if (params?.type !== 'classify') {
        throw new Error('Bad invocation')
    }
    const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { finished: false })
    const addLog = createAddLogFunction(result.logs)

    if (!getClassifyJwt().enabled) {
        const message =
            'Classify with AI is not configured. Set WORKFLOW_CLASSIFY_JWT_SECRET on the worker and Django to matching keys.'
        addLog('error', message)
        result.error = new Error(message)
        result.finished = true
        return result
    }

    // Only the first attempt counts, because a retry is the same classification.
    if (invocation.state.attempts === 0 && dailyCap && !(await dailyCap.countAndCheck(invocation.teamId))) {
        addLog(
            'warn',
            `This project reached its daily limit of ${dailyCap.dailyCap.toLocaleString('en-US')} classifications, so the step was skipped. The limit resets at midnight UTC.`
        )
        // A success that carries the skip, so a run suspended under any version of the template returns it as the step's output.
        result.invocation.state.vmState?.stack.push({
            status: 200,
            body: { category: null, confidence: null, skipped: true },
        })
        return result
    }

    const startedAt = performance.now()
    const answer = await askDjango(invocation, internalApiBaseUrl, params)
    result.invocation.state.timings.push({
        kind: 'async_function',
        duration_ms: Math.round(performance.now() - startedAt),
    })
    result.invocation.state.attempts++
    const attempt = result.invocation.state.attempts
    const failure =
        'error' in answer
            ? `Classify with AI failed on attempt ${attempt}. Error: ${fetchErrorDetail(answer.error)}.`
            : `Classify with AI failed on attempt ${attempt} with status code ${answer.status}.`

    if (isRetriable(answer) && attempt < retryPolicy.maxAttempts) {
        addLog('info', `${failure} Retrying.`)
        result.invocation.queueParameters = params
        result.invocation.queueMetadata = invocation.queueMetadata
        result.invocation.queuePriority = invocation.queuePriority
        result.invocation.queueScheduledAt = getNextRetryTime(
            retryPolicy.backoffBaseMs,
            retryPolicy.backoffMaxMs,
            attempt
        )
        return result
    }

    result.invocation.state.attempts = 0
    const response =
        'error' in answer
            ? { status: 500, body: `${answer.error.name}: ${fetchErrorDetail(answer.error)}` }
            : { status: answer.status, body: answer.body }
    if (response.status >= 400) {
        addLog('error', failure)
    }
    result.invocation.state.vmState?.stack.push(response)
    result.metrics.push({
        team_id: invocation.teamId,
        app_source_id: invocation.parentRunId ?? invocation.functionId,
        metric_kind: 'other',
        metric_name: 'fetch',
        count: 1,
    })
    return result
}
