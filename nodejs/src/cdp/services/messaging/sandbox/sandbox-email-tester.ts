import { z } from 'zod'

import { FetchResponse, internalFetch } from '~/common/utils/request'

import { ScopedServiceJwt } from '../../../utils/scoped-service-jwt'
import { HogInputsService } from '../../hog-inputs.service'
import { ActionHandlerOptions } from '../../hogflows/actions/action.interface'
import {
    SandboxEmailAction,
    SandboxEmailStepResult,
    SandboxEmailTestClient,
} from '../../hogflows/actions/email_sandbox'
import { SANDBOX_TEST_TIMEOUT_MS } from './sandbox-deadlines'
import { SandboxRenderedEmail } from './sandbox-message'
import {
    DeliveredAddressReader,
    SandboxRecipientUnavailableError,
    logRenderFailure,
    renderSandboxEmail,
} from './sandbox-render'

export const SANDBOX_TEST_TOKEN_TTL_SECONDS = 120

const TestSendResponseSchema = z.object({
    status: z.enum(['accepted', 'skipped', 'failed', 'pending']),
    reason: z.string().optional(),
    message_id: z.string().optional(),
})

export type SandboxEmailTesterDeps = {
    hogInputsService: Pick<HogInputsService, 'buildInputsWithGlobals'>
    deliveredAddress: DeliveredAddressReader
    siteUrl: string
    endpoint: string
    jwt: Pick<ScopedServiceJwt, 'enabled' | 'mint'>
    fetch?: (url: string, options: Parameters<typeof internalFetch>[1]) => Promise<FetchResponse>
}

export class SandboxEmailTester implements SandboxEmailTestClient {
    constructor(private readonly deps: SandboxEmailTesterDeps) {}

    async send(options: ActionHandlerOptions<SandboxEmailAction>): Promise<SandboxEmailStepResult> {
        let email: SandboxRenderedEmail
        try {
            email = await renderSandboxEmail(
                this.deps.hogInputsService,
                options.invocation,
                options.action,
                this.deps.siteUrl,
                this.deps.deliveredAddress
            )
        } catch (error) {
            if (error instanceof SandboxRecipientUnavailableError) {
                return { status: 'pending', reason: 'authorization_unavailable' }
            }
            logRenderFailure(options, error)
            return { status: 'failed', reason: 'render_failed' }
        }
        if (options.hogExecutorOptions?.functions) {
            return { status: 'accepted' }
        }
        if (!this.deps.endpoint || !this.deps.jwt.enabled) {
            return { status: 'failed', reason: 'sandbox_worker_unavailable' }
        }
        return this.forward(options, email)
    }

    private async forward(
        { invocation, action }: ActionHandlerOptions<SandboxEmailAction>,
        email: SandboxRenderedEmail
    ): Promise<SandboxEmailStepResult> {
        const token = this.deps.jwt.mint(
            { team_id: invocation.teamId, hog_flow_id: invocation.hogFlow.id },
            SANDBOX_TEST_TOKEN_TTL_SECONDS
        )
        let response: FetchResponse
        try {
            response = await (this.deps.fetch ?? internalFetch)(
                `${this.deps.endpoint.replace(/\/+$/, '')}/api/projects/${invocation.teamId}/sandbox_email/test_send`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                    body: JSON.stringify({
                        hog_flow_id: invocation.hogFlow.id,
                        action_id: action.id,
                        email,
                        message_category_id: action.config.message_category_id,
                        message_category_type: action.config.message_category_type,
                        email_sending_paused: Boolean(invocation.hogFlow.email_sending_paused_at),
                    }),
                    timeoutMs: SANDBOX_TEST_TIMEOUT_MS,
                }
            )
        } catch {
            return { status: 'pending', reason: 'sandbox_worker_unreachable' }
        }
        if (response.status !== 200) {
            await response.dump()
            return { status: 'failed', reason: 'sandbox_worker_unavailable' }
        }
        let body: unknown
        try {
            body = await response.json()
        } catch {
            return { status: 'pending', reason: 'sandbox_worker_unreachable' }
        }
        const parsed = TestSendResponseSchema.safeParse(body)
        return parsed.success ? parsed.data : { status: 'failed', reason: 'sandbox_worker_unavailable' }
    }
}
