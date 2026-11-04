import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { callInternalApi } from './internal-api-call'

let messageOptOutJwt: ScopedServiceJwt | undefined
const getMessageOptOutJwt = (): ScopedServiceJwt =>
    (messageOptOutJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_MESSAGE_OPT_OUT,
        defaultConfig.WORKFLOW_MESSAGE_OPT_OUT_JWT_SECRET
    ))

const OPT_OUT_TIMEOUT_MS = 10_000

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parsePayload = (args: any[]): { category_id: string; identifier: string } => {
    const [payload] = args as [{ category_id?: unknown; identifier?: unknown } | undefined]
    const categoryId = typeof payload?.category_id === 'string' ? payload.category_id.trim() : ''
    if (!categoryId) {
        throw new Error('Choose a message category')
    }
    const identifier = typeof payload?.identifier === 'string' ? payload.identifier.trim() : ''
    if (!identifier) {
        throw new Error(
            "There is no email to opt out. Check the step's recipient field, for example {person.properties.email}"
        )
    }
    return { category_id: categoryId, identifier }
}

registerAsyncFunction('postHogOptOutOfMessages', {
    execute: async (args, context, result) => {
        const payload = parsePayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Opt out of messages only runs inside a workflow')
        }

        const jwt = getMessageOptOutJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Opt out of messages is not configured. Set WORKFLOW_MESSAGE_OPT_OUT_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        // Repeating the call is safe because opting out twice leaves the recipient opted out.
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_message_opt_outs/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify(payload),
            timeoutMs: OPT_OUT_TIMEOUT_MS,
        })
    },
    mock: (args, logs) => {
        parsePayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Opt out of messages was mocked. Nobody was opted out.',
        })
        return { status: 200, body: { result: 'opted_out', detail: 'Opted out (mocked).' } }
    },
})
