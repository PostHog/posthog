import { z } from 'zod'

import type { CommonConfig } from '~/common/config'
import { defaultConfig } from '~/common/config/config'

import type { CdpConfig } from '../../config'
import type { CyclotronJobInvocationHogFunction } from '../../types'
import { PosthogJwtAudience } from '../../utils/jwt-utils'
import { ScopedServiceJwt } from '../../utils/scoped-service-jwt'
import {
    parseWorkflowStepDispatchKey,
    workflowStepDispatchKeyFromInvocation,
} from '../../utils/workflow-step-dispatch-key'
import { AWAITED_STEP_MAX_WAIT } from './step-resume.service'

// Keep in sync with get_webhook_url in products/data_warehouse/backend/logic/external_data_source/webhooks.py.
const PUBLIC_WEBHOOKS_HOSTS: Record<string, string> = {
    US: 'https://webhooks.us.posthog.com',
    EU: 'https://webhooks.eu.posthog.com',
    DEV: 'https://app.dev.posthog.dev',
}

export const WORKFLOW_STEP_CALLBACK_PATH = '/public/webhooks/workflow_callbacks'
export const WORKFLOW_STEP_CALLBACK_MAX_BODY_BYTES = 16_384

export const WorkflowStepCallbackSchema = z.object({
    status: z.enum(['completed', 'failed']).default('completed'),
    result: z.record(z.string(), z.unknown()).optional(),
})

export type WorkflowStepCallbackConfig = Pick<CdpConfig, 'WORKFLOWS_STEP_CALLBACK_JWT_SECRET'> &
    Pick<CommonConfig, 'SITE_URL' | 'CLOUD_DEPLOYMENT'>

export type WorkflowStepCallback = { teamId: number; originKey: string; jobId: string; actionId: string }

export class WorkflowStepCallbacks {
    private jwt: ScopedServiceJwt
    private publicWebhooksUrl: string

    constructor(config: WorkflowStepCallbackConfig) {
        this.jwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_STEP_CALLBACK,
            config.WORKFLOWS_STEP_CALLBACK_JWT_SECRET || '',
            AWAITED_STEP_MAX_WAIT.as('seconds')
        )
        this.publicWebhooksUrl = PUBLIC_WEBHOOKS_HOSTS[(config.CLOUD_DEPLOYMENT ?? '').toUpperCase()] ?? config.SITE_URL
    }

    get enabled(): boolean {
        return this.jwt.enabled
    }

    urlFor(invocation: CyclotronJobInvocationHogFunction): string {
        const originKey = workflowStepDispatchKeyFromInvocation(invocation)
        if (!originKey) {
            throw new Error('workflowCallbackUrl() only works in a workflow step')
        }
        if (!this.enabled) {
            throw new Error('Workflow callbacks are not configured in this environment')
        }
        const token = this.jwt.mint({ team_id: invocation.teamId, origin_key: originKey })
        return `${this.publicWebhooksUrl}${WORKFLOW_STEP_CALLBACK_PATH}/${token}`
    }

    read(token: string): WorkflowStepCallback | null {
        let claims: Record<string, unknown>
        try {
            claims = this.jwt.verify(token)
        } catch {
            return null
        }
        const { team_id: teamId, origin_key: originKey } = claims
        const key = typeof originKey === 'string' ? parseWorkflowStepDispatchKey(originKey) : null
        if (typeof teamId !== 'number' || !key) {
            return null
        }
        return { teamId, originKey: originKey as string, ...key }
    }
}

let defaultCallbacks: WorkflowStepCallbacks | undefined
export const getWorkflowStepCallbacks = (): WorkflowStepCallbacks =>
    (defaultCallbacks ??= new WorkflowStepCallbacks(defaultConfig))
