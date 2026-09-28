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

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parseClassifyPayload = (args: any[]): Record<string, unknown> => {
    const [payload] = args as [Record<string, unknown> | undefined]
    if (typeof payload?.question !== 'string' || !payload.question.trim()) {
        throw new Error('Enter a question')
    }
    const categories = payload.categories
    if (!categories || typeof categories !== 'object' || Object.keys(categories).length < 2) {
        throw new Error('Enter at least two categories')
    }
    return payload
}

registerAsyncFunction('postHogClassify', {
    execute: async (args, context, result) => {
        const payload = parseClassifyPayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Classify with Jev only runs inside a workflow')
        }

        const jwt = getClassifyJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Classify with Jev is not configured. Set WORKFLOW_CLASSIFY_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_classifications/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify(payload),
        })
    },
    mock: (args, logs) => {
        const payload = parseClassifyPayload(args)
        const categories = Object.keys(payload.categories as Record<string, unknown>)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Classify with Jev was mocked. The first category was returned without asking the model.',
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
