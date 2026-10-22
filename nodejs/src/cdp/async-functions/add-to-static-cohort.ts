import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { UUID_RE, callInternalApi } from './internal-api-call'

let addToStaticCohortJwt: ScopedServiceJwt | undefined
const getAddToStaticCohortJwt = (): ScopedServiceJwt =>
    (addToStaticCohortJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_ADD_TO_STATIC_COHORT,
        defaultConfig.WORKFLOW_ADD_TO_STATIC_COHORT_JWT_SECRET
    ))

// Django waits up to 5 seconds for another run that adds the same person, then inserts.
const ADD_TO_STATIC_COHORT_TIMEOUT_MS = 15_000

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parsePayload = (args: any[]): { cohort_id: number; person_uuid: string } => {
    const [payload] = args as [{ cohort_id?: unknown; person_uuid?: unknown } | undefined]
    const cohortId = payload?.cohort_id
    if (typeof cohortId !== 'number' || !Number.isSafeInteger(cohortId) || cohortId < 1) {
        throw new Error('Choose a static cohort')
    }
    if (typeof payload?.person_uuid !== 'string' || !UUID_RE.test(payload.person_uuid)) {
        throw new Error('This workflow run has no person to add')
    }
    return { cohort_id: cohortId, person_uuid: payload.person_uuid }
}

registerAsyncFunction('postHogAddToStaticCohort', {
    execute: async (args, context, result) => {
        const payload = parsePayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Add to static cohort only runs inside a workflow')
        }

        const jwt = getAddToStaticCohortJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Add to static cohort is not configured. Set WORKFLOW_ADD_TO_STATIC_COHORT_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        // Repeating the call is safe because Django skips a person who is already in the cohort.
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_static_cohort_members/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify(payload),
            timeoutMs: ADD_TO_STATIC_COHORT_TIMEOUT_MS,
        })
    },
    mock: (args, logs) => {
        parsePayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Add to static cohort was mocked. Nobody was added to the cohort.',
        })
        return { status: 200, body: { detail: 'The person is in the static cohort.' } }
    },
})
