import { DateTime, Duration } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { buildWorkflowStepDispatchKey } from '~/cdp/utils/workflow-step-dispatch-key'
import { instrumentFn } from '~/common/tracing/tracing-utils'

import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFlowInvocationContext,
    MinimalLogEntry,
} from '../../../types'
import { HogExecutorExecuteAsyncOptions } from '../../hog-executor-async.service'
import { EmailValidationService } from '../../messaging/email-validation.service'
import { RecipientPreferencesService } from '../../messaging/recipient-preferences.service'
import { CdpUsageReporterService } from '../../usage/cdp-usage-reporter.service'
import { trackHogFlowBillableInvocation } from '../billing-utils'
import { HogFlowFunctionsService } from '../hogflow-functions.service'
import { actionIdForLogging, findContinueAction } from '../hogflow-utils'
import { observeMissingVariableReferences } from '../hogflow-variable-usage'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'

type Action = Extract<HogFlowAction, { type: FunctionActionType }>

type AwaitingResume = NonNullable<NonNullable<HogFlowInvocationContext['currentAction']>['awaitingResume']>

// A template that starts an external run and wants the step to wait for it returns an `await` object
// next to its result: `{ ..., 'await': { 'max_wait': '190m', 'label': 'task' } }`. The step parks
// until Django wakes it by the step's dispatch key, with `max_wait` as the backstop. The template
// author sets `max_wait` to the run's own hard cap plus slack: Django fails a run at that cap and
// wakes the step, which reads as "the task failed", so the deadline only fires for a lost wake.
type AwaitRequest = { maxWait: Duration; label: string }

const AWAIT_DURATION_REGEX = /^(\d*\.?\d+)([dhms])$/
const SECONDS_PER_UNIT: Record<string, number> = { d: 86400, h: 3600, m: 60, s: 1 }
// Bounds a parked job whatever a template asks for.
const AWAIT_MAX_WAIT_CEILING = Duration.fromObject({ hours: 24 })

const parseAwaitRequest = (execResult: unknown): AwaitRequest | null => {
    const request = (execResult as { await?: unknown } | undefined)?.await
    if (!request || typeof request !== 'object') {
        return null
    }
    const { max_wait: maxWait, label } = request as { max_wait?: unknown; label?: unknown }
    const match = typeof maxWait === 'string' ? AWAIT_DURATION_REGEX.exec(maxWait) : null
    if (!match) {
        return null
    }
    const requested = Duration.fromObject({ seconds: parseFloat(match[1]) * SECONDS_PER_UNIT[match[2]] })
    return {
        maxWait: requested > AWAIT_MAX_WAIT_CEILING ? AWAIT_MAX_WAIT_CEILING : requested,
        label: typeof label === 'string' && label ? label : 'run',
    }
}

const humanDuration = (duration: Duration): string => duration.rescale().toHuman()

// The step result is what `output_variable` stores, and the executor fails the step when total
// workflow variables pass its 5KB cap. Strings in the result are cut to what still fits, with room
// left for the ids, the status, and the keys themselves.
const RESUME_RESULT_STRING_CAP = 1500
const VARIABLES_BYTE_CAP = 5120
const VARIABLES_HEADROOM_BYTES = 512

const counterAwaitedStepStaleResume = new Counter({
    name: 'cdp_hogflow_awaited_step_stale_resume',
    help: 'A parked step received a wake keyed to an earlier visit of the same step and kept waiting.',
})

const resumeStringCap = (variables: Record<string, unknown>): number => {
    const used = Buffer.byteLength(JSON.stringify(variables), 'utf8')
    return Math.max(0, Math.min(RESUME_RESULT_STRING_CAP, VARIABLES_BYTE_CAP - VARIABLES_HEADROOM_BYTES - used))
}

// A string cut to zero is dropped rather than stored empty, so a template reading it sees "unset".
const truncateStringValues = (obj: Record<string, unknown>, cap: number): Record<string, unknown> =>
    Object.fromEntries(
        Object.entries(obj)
            .filter(([, value]) => !(typeof value === 'string' && cap === 0))
            .map(([key, value]) => [key, typeof value === 'string' && value.length > cap ? value.slice(0, cap) : value])
    )

export class HogFunctionHandler implements ActionHandler {
    constructor(
        private hogFlowFunctionsService: HogFlowFunctionsService,
        private recipientPreferencesService: RecipientPreferencesService,
        private emailValidationService: EmailValidationService,
        private hogFlowActionBillingType: 'fetch' | 'email' | 'push',
        private usageReporter?: CdpUsageReporterService,
        private options: { awaitedStepsEnabled?: boolean } = {}
    ) {}

    async execute({
        invocation,
        action,
        result,
        hogExecutorOptions,
    }: ActionHandlerOptions<Action>): Promise<ActionHandlerResult> {
        const awaitedStepsEnabled = this.options.awaitedStepsEnabled ?? false
        const awaiting = invocation.state.currentAction?.awaitingResume
        // A parked step re-enters here on wake or deadline. Nothing below must run again: the
        // dispatch already happened and was billed, and the variable-usage guard below keys on
        // hogFunctionState, which a finished function never sets.
        if (awaitedStepsEnabled && awaiting) {
            return this.resumeAwaitedStep(invocation, action, result, awaiting)
        }

        // Inputs are rendered once, on fresh entry into the action (continuations reuse the
        // rendered state in hogFunctionState) - so this also fires at most once per step per run
        if (!invocation.state.currentAction?.hogFunctionState) {
            observeMissingVariableReferences(invocation, action, result)
        }

        const functionResult = await this.executeHogFunction(invocation, action, hogExecutorOptions)

        // Add all logs
        functionResult.logs.forEach((log: MinimalLogEntry) => {
            result.logs.push({
                level: log.level,
                timestamp: log.timestamp,
                message: `${actionIdForLogging(action)} ${log.message}`,
            })
        })

        // Collect captured PostHog events and metrics from the function execution
        result.capturedPostHogEvents = [...result.capturedPostHogEvents, ...functionResult.capturedPostHogEvents]
        // Collect warehouse webhook payloads
        result.warehouseWebhookPayloads = [
            ...result.warehouseWebhookPayloads,
            ...functionResult.warehouseWebhookPayloads,
        ]
        result.metrics = [...result.metrics, ...functionResult.metrics]
        result.messageAssets = [...result.messageAssets, ...functionResult.messageAssets]

        if (!functionResult.finished) {
            // Set the state of the function result on the substate of the flow for the next execution
            result.invocation.state.currentAction!.hogFunctionState = functionResult.invocation.state
            // Preserve queue routing and parameters from the function result
            result.invocation.queue = functionResult.invocation.queue
            result.invocation.queuePriority = functionResult.invocation.queuePriority
            result.invocation.queueParameters = functionResult.invocation.queueParameters
            result.invocation.queueMetadata = functionResult.invocation.queueMetadata
            // Routing-only reschedule signature: the queue changed AND no explicit
            // `queueScheduledAt` was set. That's the shape produced by `routeEmailToQueue`
            // and `routeToQueue` in hog-executor.service.ts when moving a job between the
            // hogflow and email queues — the next dequeue continues the same action on the
            // new queue. Tag the action state so the executor can suppress the redundant
            // "Resuming..." / "Workflow will pause until..." pair on the next dequeue.
            //
            // The queue-changed check is what keeps async pauses (fetches, SES throttle
            // retries) out of this branch: both keep `queueScheduledAt` set OR leave the
            // queue unchanged, so they don't satisfy both halves of the condition.
            const queueChanged = functionResult.invocation.queue !== invocation.queue
            if (queueChanged && !functionResult.invocation.queueScheduledAt) {
                result.invocation.state.currentAction!.routingOnlyReschedule = true
            }
            return {
                scheduledAt: functionResult.invocation.queueScheduledAt ?? DateTime.now(),
            }
        }

        // Add billable_invocation metric only if the function actually executed (not skipped)
        if (!functionResult.skipped) {
            trackHogFlowBillableInvocation(result, {
                invocation: functionResult.invocation,
                billingMetricType: this.hogFlowActionBillingType,
            })

            // actionStepCount holds across a retry of this step but changes on a loop revisit.
            this.usageReporter?.reportBillableInvocation({
                teamId: invocation.teamId,
                recordId: `flow:${invocation.id}:${invocation.state.actionStepCount}:${this.hogFlowActionBillingType}`,
            })

            // Re-pin the attribution version to the one that actually sent. Live edits reach runs
            // already in flight, so a run that entered on v2 can send its email after v3 is
            // published — and the conversion belongs to the version whose message the person
            // received, which is also the version `email_sent` was counted under. Leaving the
            // run-start stamp here would split a rate across two versions.
            if (this.hogFlowActionBillingType === 'email' || this.hogFlowActionBillingType === 'push') {
                result.invocation.state.flowVersion = invocation.hogFlow.version
            }
        }

        const awaitRequest =
            awaitedStepsEnabled && !functionResult.error ? parseAwaitRequest(functionResult.execResult) : null
        if (awaitRequest) {
            return this.parkForAwaitedRun(invocation, action, result, awaitRequest, functionResult.execResult)
        }

        return {
            nextAction: findContinueAction(invocation),
            result: functionResult.execResult,
            error: functionResult.error,
        }
    }

    private parkForAwaitedRun(
        invocation: CyclotronJobInvocationHogFlow,
        action: Action,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        awaitRequest: AwaitRequest,
        execResult: unknown
    ): ActionHandlerResult {
        const { await: _await, ...dispatch } = execResult as Record<string, unknown>
        const key = buildWorkflowStepDispatchKey(invocation.id, action.id, invocation.state.actionStepCount)
        const deadline = DateTime.now().plus(awaitRequest.maxWait)
        result.invocation.state.currentAction!.awaitingResume = {
            key,
            deadlineAt: deadline.toISO()!,
            dispatch,
            label: awaitRequest.label,
        }
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `${actionIdForLogging(action)} Waiting for the ${awaitRequest.label} to finish (up to ${humanDuration(awaitRequest.maxWait)})`,
        })
        // The dispatch ids are stored now, not only on resume, so a step that later fails still
        // leaves them in variables for the steps `on_error: continue` carries on to.
        return { scheduledAt: deadline, result: dispatch }
    }

    private resumeAwaitedStep(
        invocation: CyclotronJobInvocationHogFlow,
        action: Action,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        awaiting: AwaitingResume
    ): ActionHandlerResult {
        const currentAction = result.invocation.state.currentAction!
        const label = awaiting.label ?? 'run'
        const resume = currentAction.resumeResult
        if (resume?.key === awaiting.key) {
            delete currentAction.awaitingResume
            delete currentAction.resumeResult
            const payload = truncateStringValues(
                resume.result ?? {},
                resumeStringCap(result.invocation.state.variables ?? {})
            )
            if (resume.status !== 'completed') {
                const detail = typeof payload.error_message === 'string' ? `: ${payload.error_message}` : ''
                const outcome = resume.status === 'cancelled' ? 'was cancelled' : 'failed'
                throw new Error(`The ${label} ${outcome}${detail}`)
            }
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `${actionIdForLogging(action)} The ${label} finished`,
            })
            return {
                nextAction: findContinueAction(invocation),
                result: { ...awaiting.dispatch, status: resume.status, ...payload },
            }
        }
        if (resume) {
            delete currentAction.resumeResult
            counterAwaitedStepStaleResume.inc()
        }
        const deadline = DateTime.fromISO(awaiting.deadlineAt)
        if (DateTime.now() >= deadline) {
            throw new Error(`Timed out waiting for the ${label} to finish`)
        }
        // Woken before the deadline with nothing to consume (clock skew between Postgres and this
        // worker is the known cause): park again until the deadline.
        return { scheduledAt: deadline }
    }

    private async executeHogFunction(
        invocation: CyclotronJobInvocationHogFlow,
        action: Action,
        hogExecutorOptions?: HogExecutorExecuteAsyncOptions
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> & { skipped?: boolean }> {
        const hogFunction = await instrumentFn(
            { key: 'hogFlow.action.hogFunction.buildHogFunction', sendException: false },
            () => this.hogFlowFunctionsService.buildHogFunction(invocation.hogFlow, action.config)
        )
        const hogFunctionInvocation = await instrumentFn(
            { key: 'hogFlow.action.hogFunction.buildInvocation', sendException: false },
            () =>
                this.hogFlowFunctionsService.buildHogFunctionInvocation(invocation, hogFunction, {
                    event: invocation.state.event,
                    person: invocation.person,
                    groups: invocation.groups,
                    variables: invocation.state.variables,
                })
        )

        const skipReason = await instrumentFn(
            { key: 'hogFlow.action.hogFunction.recipientPreferences', sendException: false },
            () => this.recipientPreferencesService.shouldSkipAction(hogFunctionInvocation, action)
        )
        if (skipReason) {
            // Suppression and opt-out both short-circuit the send, but a customer reading the run
            // log needs to know which one — the operator response is different (fix the recipient
            // list vs. respect the unsubscribe). `email_suppressed` mirrors the metric name the
            // send-time choke point in email.service.ts emits, so both entry points aggregate.
            const message =
                skipReason === 'suppressed'
                    ? `Skipping send: recipient is on the suppression list.`
                    : `Recipient has opted out, skipping message delivery.`
            const metrics =
                skipReason === 'suppressed'
                    ? [
                          {
                              team_id: hogFunctionInvocation.teamId,
                              app_source_id: hogFunctionInvocation.functionId,
                              instance_id: action.id,
                              metric_kind: 'email' as const,
                              metric_name: 'email_suppressed' as const,
                              count: 1,
                          },
                      ]
                    : []
            return {
                finished: true,
                skipped: true,
                invocation: hogFunctionInvocation,
                logs: [{ level: 'info', timestamp: DateTime.now(), message }],
                metrics,
                capturedPostHogEvents: [],
                warehouseWebhookPayloads: [],
                messageAssets: [],
                conversionWatchers: [],
            }
        }

        // Predicted hard bounce (bad syntax / dead domain): skip before the send reaches
        // SES so it never counts against our bounce rate. Runs after the opt-out check so
        // an opted-out recipient never triggers a DNS lookup.
        const emailSkipReason = await instrumentFn(
            { key: 'hogFlow.action.hogFunction.emailValidation', sendException: false },
            () => this.emailValidationService.getSkipReason(hogFunctionInvocation, action)
        )
        if (emailSkipReason) {
            return {
                finished: true,
                skipped: true,
                invocation: hogFunctionInvocation,
                logs: [{ level: 'info', timestamp: DateTime.now(), message: emailSkipReason }],
                metrics: [
                    {
                        team_id: hogFunctionInvocation.teamId,
                        app_source_id: hogFunctionInvocation.functionId,
                        instance_id: action.id,
                        metric_kind: 'email',
                        metric_name: 'email_bounce_prevented',
                        count: 1,
                    },
                ],
                capturedPostHogEvents: [],
                warehouseWebhookPayloads: [],
                messageAssets: [],
                conversionWatchers: [],
            }
        }

        return instrumentFn({ key: 'hogFlow.action.hogFunction.executeWithAsyncFunctions', sendException: false }, () =>
            this.hogFlowFunctionsService.executeWithAsyncFunctions(hogFunctionInvocation, hogExecutorOptions)
        )
    }
}
