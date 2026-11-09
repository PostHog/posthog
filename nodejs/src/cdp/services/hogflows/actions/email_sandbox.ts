import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'

import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult, SandboxEmailOutcome } from '../../../types'
import { actionIdForLogging, findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

export type SandboxEmailAction = Extract<HogFlowAction, { type: 'email_sandbox' }>

export type SandboxEmailStepResult = {
    status: 'accepted' | 'skipped' | 'failed' | 'pending'
    reason?: string
    message_id?: string
}

export type SandboxEmailSendDecision = SandboxEmailOutcome | { retryAt: DateTime }

export interface SandboxEmailStep {
    send(options: ActionHandlerOptions<SandboxEmailAction>): Promise<SandboxEmailSendDecision>
}

export interface SandboxEmailTestClient {
    send(options: ActionHandlerOptions<SandboxEmailAction>): Promise<SandboxEmailStepResult>
}

export const SANDBOX_QUEUE = 'emailsandbox'
const SENDING_DISABLED: SandboxEmailOutcome = { outcome: 'skipped', reason: 'sending_disabled' }
const WORKER_UNAVAILABLE: SandboxEmailOutcome = { outcome: 'failed', reason: 'sandbox_worker_unavailable' }

export class SandboxEmailActionHandler implements ActionHandler {
    constructor(
        private readonly config: { enabled: boolean },
        private readonly sendStep: SandboxEmailStep | null,
        private readonly testClient: SandboxEmailTestClient | null
    ) {}

    async execute(options: ActionHandlerOptions<SandboxEmailAction>): Promise<ActionHandlerResult> {
        const { invocation, result, hogExecutorOptions } = options
        const onSandboxQueue = invocation.queue === SANDBOX_QUEUE
        const stored = invocation.state.currentAction?.sandboxEmail

        if (stored) {
            return onSandboxQueue ? this.handBack(result, stored) : this.finish(options, toStepResult(stored))
        }
        if (!this.config.enabled) {
            return onSandboxQueue
                ? this.handBack(result, SENDING_DISABLED)
                : this.finish(options, toStepResult(SENDING_DISABLED))
        }
        if (hogExecutorOptions?.isTest) {
            return this.runTest(options)
        }
        if (!onSandboxQueue) {
            return this.routeToSandboxQueue(invocation, result)
        }
        return this.sendOnSandboxQueue(options)
    }

    private async runTest(options: ActionHandlerOptions<SandboxEmailAction>): Promise<ActionHandlerResult> {
        if (options.hogExecutorOptions?.functions) {
            this.log(options, 'Mocked the sandbox email send')
            return this.finish(options, { status: 'accepted' })
        }
        if (!this.testClient) {
            return this.finish(options, toStepResult(WORKER_UNAVAILABLE))
        }
        return this.finish(options, await this.testClient.send(options))
    }

    private routeToSandboxQueue(
        invocation: CyclotronJobInvocationHogFlow,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    ): ActionHandlerResult {
        result.invocation.queue = SANDBOX_QUEUE
        result.invocation.queueParameters = null
        result.invocation.queuePriority = priorityOutsideEmailQueue(invocation)
        result.invocation.queueMetadata = undefined
        result.invocation.state.currentAction!.routingOnlyReschedule = true
        return { scheduledAt: DateTime.now() }
    }

    private async sendOnSandboxQueue(options: ActionHandlerOptions<SandboxEmailAction>): Promise<ActionHandlerResult> {
        if (!this.sendStep) {
            return this.handBack(options.result, WORKER_UNAVAILABLE)
        }
        const decision = await this.sendStep.send(options)
        if ('retryAt' in decision) {
            return { scheduledAt: decision.retryAt }
        }
        if (decision.outcome === 'accepted') {
            options.result.invocation.state.flowVersion = options.invocation.hogFlow.version
        }
        return this.handBack(options.result, decision)
    }

    private handBack(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        outcome: SandboxEmailOutcome
    ): ActionHandlerResult {
        const currentAction = result.invocation.state.currentAction!
        currentAction.sandboxEmail = outcome
        currentAction.routingOnlyReschedule = true
        result.invocation.queue = 'hogflow'
        result.invocation.queueParameters = null
        return { scheduledAt: DateTime.now() }
    }

    private finish(
        options: ActionHandlerOptions<SandboxEmailAction>,
        stepResult: SandboxEmailStepResult
    ): ActionHandlerResult {
        if (stepResult.status === 'failed') {
            return { result: stepResult, error: new Error(`Sandbox email was not sent: ${stepResult.reason}`) }
        }
        this.log(
            options,
            stepResult.status === 'accepted'
                ? 'Sandbox email accepted for delivery'
                : `Sandbox email was not sent (${stepResult.status}): ${stepResult.reason}`
        )
        return { result: stepResult, nextAction: findContinueAction(options.invocation) }
    }

    private log({ action, result }: ActionHandlerOptions<SandboxEmailAction>, message: string): void {
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `${actionIdForLogging(action)} ${message}`,
        })
    }
}

function toStepResult({ outcome, reason, messageId }: SandboxEmailOutcome): SandboxEmailStepResult {
    return { status: outcome, ...(reason ? { reason } : {}), ...(messageId ? { message_id: messageId } : {}) }
}

function priorityOutsideEmailQueue(invocation: CyclotronJobInvocationHogFlow): number {
    const originPriority = invocation.queue === 'email' ? invocation.queueMetadata?.originPriority : undefined
    return typeof originPriority === 'number' ? originPriority : invocation.queuePriority
}
