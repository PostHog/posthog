import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { workflowStepDispatchKeyFromInvocation } from '../utils/workflow-step-dispatch-key'

// The token rides the staged fetch verbatim through every engine retry (executeFetch re-queues
// the identical request), so its lifetime must cover the whole backoff chain plus queue lag,
// not one attempt. An expired token 401s, which is not retriable, so the step fails permanently.
// The claims scope it to a single team and workflow, which keeps the longer window cheap.
const TOKEN_TTL_SECONDS = 30 * 60

// Matches MAX_RUN_NOTE_CHARS in products/signals/backend/scout_harness/limits.py. The note renders
// from event properties, so a long value is cut here instead of failing the step with a 400.
const MAX_NOTE_CHARS = 1000

// Counts code points, as Python's max_length does, so a cut note never splits a surrogate pair.
const truncateNote = (note: string): string => Array.from(note).slice(0, MAX_NOTE_CHARS).join('')

// Its own key, not postHogCreateTask's — see products/workflows/backend/service_jwt.py for why.
let scoutRunJwt: ScopedServiceJwt | undefined
const getScoutRunJwt = (): ScopedServiceJwt =>
    (scoutRunJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_SCOUT_RUN,
        defaultConfig.WORKFLOW_SCOUT_RUN_JWT_SECRET
    ))

registerAsyncFunction('postHogRunScout', {
    execute: (args, context, result) => {
        const [payload] = args as [Record<string, any> | undefined]

        if (!payload?.skill_name || typeof payload.skill_name !== 'string') {
            throw new Error("postHogRunScout call missing 'skill_name' property")
        }

        // Both come from the flow-spawned invocation, never from step inputs: the hog_flow_id
        // claim is what the endpoint trusts to resolve the calling workflow, and the dispatch key
        // scopes the idempotency key to this step and visit (the run id alone is shared by every
        // step in the run, so two run-scout steps in one workflow would dedupe against each other).
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const idempotencyKey = workflowStepDispatchKeyFromInvocation(context.invocation)
        if (!hogFlow?.id || !idempotencyKey) {
            throw new Error('postHogRunScout only runs inside a workflow')
        }

        const jwt = getScoutRunJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Running scouts from a workflow is not configured in this environment (WORKFLOW_SCOUT_RUN_JWT_SECRET unset)'
            )
        }
        const token = jwt.mint({ team_id: context.invocation.teamId, hog_flow_id: hogFlow.id }, TOKEN_TTL_SECONDS)
        const note = typeof payload.note === 'string' ? truncateNote(payload.note.trim()) : ''

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/projects/${context.invocation.teamId}/workflow_scout_runs/`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
                skill_name: payload.skill_name,
                idempotency_key: idempotencyKey,
                ...(note ? { note } : {}),
            }),
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogRunScout' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogRunScout(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 202,
            body: { scout: (args[0] as Record<string, any> | undefined)?.skill_name, workflow_id: 'mock-workflow-id' },
        }
    },
})
