import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { callInternalApi } from './internal-api-call'

let classifyJwt: ScopedServiceJwt | undefined
const getClassifyJwt = (): ScopedServiceJwt =>
    (classifyJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_CLASSIFY,
        defaultConfig.WORKFLOW_CLASSIFY_JWT_SECRET
    ))

// Django gives the gateway 5 seconds (TIMEOUT_SECONDS in workflow_classifications.py) and returns a 503
// on a gateway timeout, which this worker retries. The worker budget must be longer than that plus Django's
// own work. That 5 seconds limits each network operation, not the whole call, so Django can still overrun
// this budget. The worker does not retry its own timeout, because the gateway may still be answering the
// first request and a retry would pay for the same classification again.
const CLASSIFY_TIMEOUT_MS = 7000

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
    execute: async (args, context, result) => {
        const payload = parseClassifyPayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Classify with AI only runs inside a workflow')
        }

        const jwt = getClassifyJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Classify with AI is not configured. Set WORKFLOW_CLASSIFY_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_classifications/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify(payload),
            timeoutMs: CLASSIFY_TIMEOUT_MS,
            retryOnTimeout: false,
        })
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
