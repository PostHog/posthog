import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'

let classificationJwt: ScopedServiceJwt | undefined
const getClassificationJwt = (): ScopedServiceJwt =>
    (classificationJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_CLASSIFICATION,
        defaultConfig.WORKFLOW_CLASSIFICATION_JWT_SECRET
    ))

registerAsyncFunction('postHogClassify', {
    execute: (args, context, result) => {
        const [payload] = args as [Record<string, unknown> | undefined]
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('postHogClassify only runs inside a workflow')
        }
        if (!payload || typeof payload.text !== 'string' || typeof payload.instructions !== 'string') {
            throw new Error('Classification requires text and instructions')
        }
        const jwt = getClassificationJwt()
        if (!jwt.enabled) {
            throw new Error('Workflow classification is not configured (WORKFLOW_CLASSIFICATION_JWT_SECRET unset)')
        }
        // The queued request retains its token across backoff and queue lag.
        const token = jwt.mint({ team_id: context.invocation.teamId, hog_flow_id: hogFlow.id }, 30 * 60)
        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/projects/${context.invocation.teamId}/workflow_classifications/`,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ text: payload.text, instructions: payload.instructions, labels: payload.labels }),
        })
    },
    mock: (args, logs) => {
        logs.push({ level: 'info', timestamp: DateTime.now(), message: 'JEV classification was mocked.' })
        const labels = (args[0] as { labels?: Record<string, string> } | undefined)?.labels ?? {}
        const label = Object.keys(labels)[0] ?? 'mock-label'
        const probabilities = Object.fromEntries(Object.keys(labels).map((key) => [key, key === label ? 1 : 0]))
        return { status: 200, body: { label, confidence: 1, probabilities } }
    },
})
