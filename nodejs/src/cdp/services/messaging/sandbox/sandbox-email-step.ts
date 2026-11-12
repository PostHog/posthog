import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow, SandboxEmailOutcome } from '../../../types'
import { buildWorkflowStepDispatchKey } from '../../../utils/workflow-step-dispatch-key'
import { HogInputsService } from '../../hog-inputs.service'
import { ActionHandlerOptions } from '../../hogflows/actions/action.interface'
import { SandboxEmailAction, SandboxEmailSendDecision, SandboxEmailStep } from '../../hogflows/actions/email_sandbox'
import { RecipientPreferencesService } from '../recipient-preferences.service'
import { SandboxEmailEvents, sandboxAppMetric } from './sandbox-email-events'
import { SandboxEmailService, SandboxSendOutcome } from './sandbox-email.service'
import {
    DeliveredAddressReader,
    SandboxRecipientUnavailableError,
    logRenderFailure,
    renderSandboxEmail,
} from './sandbox-render'
import { SandboxSesBucket, claimSesSlot } from './sandbox-ses-bucket'

export const MAX_SANDBOX_RETRIES = 8
const FIRST_RETRY_DELAY_MS = 30_000
const MAX_RETRY_DELAY_MS = 15 * 60_000
const RETRY_JITTER = 0.2

export function sandboxRetryDelayMs(retry: number, random: () => number = Math.random): number {
    const ceiling = Math.min(MAX_RETRY_DELAY_MS, FIRST_RETRY_DELAY_MS * 2 ** retry)
    return ceiling * (1 - RETRY_JITTER + RETRY_JITTER * random())
}

export type SandboxEmailSendStepDeps = {
    service: Pick<SandboxEmailService, 'send'>
    hogInputsService: Pick<HogInputsService, 'buildInputsWithGlobals'>
    deliveredAddress: DeliveredAddressReader
    siteUrl: string
    recipientPreferences: Pick<RecipientPreferencesService, 'checkMarketingFrequencyCap'>
    events: Pick<SandboxEmailEvents, 'capture'>
    sesBucket: SandboxSesBucket
}

export class SandboxEmailSendStep implements SandboxEmailStep {
    constructor(private readonly deps: SandboxEmailSendStepDeps) {}

    async send(options: ActionHandlerOptions<SandboxEmailAction>): Promise<SandboxEmailSendDecision> {
        const { invocation, action, result } = options
        const attempt = await this.attempt(options)
        if (attempt.status !== 'retry') {
            return this.record(invocation, action, result.metrics, toOutcome(attempt))
        }
        const retries = invocation.state.currentAction?.sandboxEmailRetries ?? 0
        if (retries >= MAX_SANDBOX_RETRIES) {
            return this.record(invocation, action, result.metrics, {
                outcome: 'failed',
                reason: 'retries_exhausted',
                retries,
            })
        }
        result.invocation.state.currentAction!.sandboxEmailRetries = retries + 1
        if (attempt.reason === 'ses_transient') {
            result.invocation.state.currentAction!.sandboxEmailUncertainSends = uncertainSends(invocation) + 1
        }
        return { retryAt: DateTime.now().plus({ milliseconds: sandboxRetryDelayMs(retries) }) }
    }

    private async attempt(options: ActionHandlerOptions<SandboxEmailAction>): Promise<SandboxSendOutcome> {
        const { invocation, action } = options
        let email: unknown
        try {
            email = await renderSandboxEmail(
                this.deps.hogInputsService,
                invocation,
                action,
                this.deps.siteUrl,
                this.deps.deliveredAddress
            )
        } catch (error) {
            if (error instanceof SandboxRecipientUnavailableError) {
                return { status: 'retry', reason: 'authorization_unavailable' }
            }
            logRenderFailure(options, error)
            return { status: 'failed', reason: 'render_failed' }
        }
        return this.deps.service.send({
            teamId: invocation.teamId,
            hogFlowId: invocation.hogFlow.id,
            invocationId: invocation.id,
            actionId: action.id,
            flowVersion: invocation.hogFlow.version,
            isTest: false,
            workflowEmailPaused: Boolean(invocation.hogFlow.email_sending_paused_at),
            parentRunId: invocation.parentRunId ?? undefined,
            email,
            categoryId: action.config.message_category_id,
            categoryType: action.config.message_category_type,
            optOuts: invocation.state.messageOptOuts,
            capClaimId: `${stepVisitKey(invocation, action)}/${uncertainSends(invocation)}`,
            claimSesSlot: () => claimSesSlot(this.deps.sesBucket),
            frequencyCap: () =>
                this.deps.recipientPreferences.checkMarketingFrequencyCap({
                    teamId: invocation.teamId,
                    resolvePersonId: () => Promise.resolve(invocation.person?.id),
                    dispatchKey: stepVisitKey(invocation, action),
                }),
        })
    }

    private record(
        invocation: CyclotronJobInvocationHogFlow,
        action: SandboxEmailAction,
        metrics: ActionHandlerOptions<SandboxEmailAction>['result']['metrics'],
        outcome: SandboxEmailOutcome
    ): SandboxEmailOutcome {
        metrics.push(
            sandboxAppMetric(outcome.outcome, {
                teamId: invocation.teamId,
                appSourceId: invocation.parentRunId ?? invocation.hogFlow.id,
                actionId: action.id,
            })
        )
        void this.deps.events.capture(invocation.teamId, outcome.outcome, {
            workflow_id: invocation.hogFlow.id,
            action_id: action.id,
            is_test: false,
            ...(outcome.reason ? { reason: outcome.reason } : {}),
        })
        return outcome
    }
}

function toOutcome(attempt: Exclude<SandboxSendOutcome, { status: 'retry' }>): SandboxEmailOutcome {
    return attempt.status === 'accepted'
        ? { outcome: 'accepted', messageId: attempt.messageId }
        : { outcome: attempt.status, reason: attempt.reason }
}

function uncertainSends(invocation: CyclotronJobInvocationHogFlow): number {
    return invocation.state.currentAction?.sandboxEmailUncertainSends ?? 0
}

function stepVisitKey(invocation: CyclotronJobInvocationHogFlow, action: SandboxEmailAction): string {
    const { actionStepCount, rerunAttempts } = invocation.state
    return actionStepCount === undefined
        ? `${invocation.id}:${action.id}`
        : buildWorkflowStepDispatchKey(invocation.id, action.id, actionStepCount, rerunAttempts)
}
