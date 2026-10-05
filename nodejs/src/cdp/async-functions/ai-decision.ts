import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { callInternalApi } from './internal-api-call'

let aiDecisionJwt: ScopedServiceJwt | undefined
const getAiDecisionJwt = (): ScopedServiceJwt =>
    (aiDecisionJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_AI_DECISION,
        defaultConfig.WORKFLOW_AI_DECISION_JWT_SECRET
    ))

// Longer than Django's gateway timeout (TIMEOUT_SECONDS in workflow_ai_decisions.py), so the worker receives
// Django's retriable 503 instead of aborting first and asking the gateway the same question again.
const AI_DECISION_TIMEOUT_MS = 7000

// Match the limits of the decision endpoint (MAX_OPTIONS and the options field in workflow_ai_decisions.py),
// so a mocked test run fails on the same inputs as a live run.
const MAX_OPTIONS = 16
const MAX_DESCRIPTION_LENGTH = 500
const MAX_CONTEXT_CHARS = 65_536

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parseAiDecisionPayload = (args: any[]): Record<string, unknown> => {
    const [payload] = args as [Record<string, unknown> | undefined]
    if (typeof payload?.question !== 'string' || !payload.question.trim()) {
        throw new Error('Enter a question')
    }
    const options = payload.options
    if (!options || typeof options !== 'object' || Object.keys(options).length < 2) {
        throw new Error('Enter at least two options')
    }
    if (Object.keys(options).length > MAX_OPTIONS) {
        throw new Error(`Enter at most ${MAX_OPTIONS} options`)
    }
    if (
        Object.values(options).some(
            (description) => typeof description === 'string' && [...description.trim()].length > MAX_DESCRIPTION_LENGTH
        )
    ) {
        throw new Error(`Keep each option description to ${MAX_DESCRIPTION_LENGTH} characters or fewer`)
    }
    if ([...(JSON.stringify(payload.context) ?? '')].length > MAX_CONTEXT_CHARS) {
        throw new Error(`Keep the context to ${MAX_CONTEXT_CHARS} characters of JSON or fewer`)
    }
    return payload
}

registerAsyncFunction('postHogAiDecision', {
    execute: async (args, context, result) => {
        const payload = parseAiDecisionPayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('AI decision only runs inside a workflow')
        }

        const jwt = getAiDecisionJwt()
        if (!jwt.enabled) {
            throw new Error(
                'AI decision is not configured. Set WORKFLOW_AI_DECISION_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_ai_decisions/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify(payload),
            timeoutMs: AI_DECISION_TIMEOUT_MS,
        })
    },
    mock: (args, logs) => {
        const payload = parseAiDecisionPayload(args)
        const [firstOption] = Object.keys(payload.options as Record<string, unknown>)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'AI decision was mocked. The first option was returned without asking the model.',
        })
        return { status: 200, body: { decision: firstOption, confidence: 1 } }
    },
})
