import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { UUID_RE, callInternalApi } from './internal-api-call'

let cohortMembershipJwt: ScopedServiceJwt | undefined
const getCohortMembershipJwt = (): ScopedServiceJwt =>
    (cohortMembershipJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_ADD_STATIC_COHORT_MEMBER,
        defaultConfig.WORKFLOW_ADD_STATIC_COHORT_MEMBER_JWT_SECRET
    ))

const parsePayload = (args: any[]): { cohort_id: number; person_uuid: string } => {
    const [payload] = args as [{ cohort_id?: unknown; person_uuid?: unknown } | undefined]
    if (!Number.isSafeInteger(payload?.cohort_id) || Number(payload?.cohort_id) < 1) {
        throw new Error('Select a static cohort')
    }
    if (typeof payload?.person_uuid !== 'string' || !UUID_RE.test(payload.person_uuid)) {
        throw new Error('This workflow run has no person')
    }
    return { cohort_id: Number(payload.cohort_id), person_uuid: payload.person_uuid }
}

registerAsyncFunction('postHogAddPersonToStaticCohort', {
    execute: async (args, context, result) => {
        const payload = parsePayload(args)
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Add person to static cohort only runs inside a workflow')
        }

        const jwt = getCohortMembershipJwt()
        if (!jwt.enabled) {
            throw new Error('Add person to static cohort is not configured')
        }
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_cohort_memberships/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify(payload),
            timeoutMs: 30_000,
            retryOnTimeout: false,
        })
    },
    mock: (args, logs) => {
        parsePayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Person was added to the static cohort (mocked).',
        })
        return { status: 200, body: { result: 'added', detail: 'Person was added to the static cohort.' } }
    },
})
