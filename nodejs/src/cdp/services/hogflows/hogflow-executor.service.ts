import { get } from 'lodash'
import { DateTime } from 'luxon'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { logger } from '~/common/utils/logger'
import { UUIDT } from '~/common/utils/utils'

import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFunctionCapturedEvent,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    LogEntry,
    LogEntryLevel,
    MessageAssetRow,
    MinimalAppMetric,
    MinimalLogEntry,
    WarehouseWebhookPayload,
} from '../../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../../utils/hog-function-filtering'
import { createInvocationResult } from '../../utils/invocation-utils'
import { HogExecutorExecuteAsyncOptions } from '../hog-executor.service'
import { EmailValidationService } from '../messaging/email-validation.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { ActionHandler } from './actions/action.interface'
import { ConditionalBranchHandler } from './actions/conditional_branch'
import { DelayHandler } from './actions/delay'
import { ExitHandler } from './actions/exit.handler'
import { HogFunctionHandler } from './actions/hog_function'
import { RandomCohortBranchHandler } from './actions/random_cohort_branch'
import { TriggerHandler } from './actions/trigger.handler'
import { WaitUntilTimeWindowHandler } from './actions/wait_until_time_window'
import { HogFlowDuplicateObserverService } from './hogflow-duplicate-observer.service'
import { HogFlowFunctionsService } from './hogflow-functions.service'
import {
    actionIdForLogging,
    ensureCurrentAction,
    findContinueAction,
    shouldSkipAction,
    trackE2eLag,
} from './hogflow-utils'

export const MAX_ACTION_STEPS_HARD_LIMIT = 1000

export function createHogFlowInvocation(
    globals: HogFunctionInvocationGlobals,
    hogFlow: HogFlow,
    filterGlobals: HogFunctionFilterGlobals
): CyclotronJobInvocationHogFlow {
    // Build default variables from hogFlow, then merge in any provided in globals.variables
    const defaultVariables =
        hogFlow.variables?.reduce(
            (acc, variable) => {
                acc[variable.key] = variable.default || null
                return acc
            },
            {} as Record<string, any>
        ) || {}

    const mergedVariables = {
        ...defaultVariables,
        ...(globals.variables || {}),
    }

    return {
        id: new UUIDT().toString(),
        state: {
            event: globals.event,
            actionStepCount: 0,
            variables: mergedVariables,
        },
        teamId: hogFlow.team_id,
        functionId: hogFlow.id, // TODO: Include version?
        hogFlow,
        person: globals.person, // This is outside of state as we don't persist it
        groups: globals.groups, // Same as person: in-memory only (test path); real execution re-resolves on dequeue
        filterGlobals,
        queue: 'hogflow',
        queuePriority: 1,
    }
}

export class HogFlowExecutorService {
    private readonly actionHandlers: Record<HogFlowAction['type'], ActionHandler>
    private readonly duplicateObserver: HogFlowDuplicateObserverService | null

    constructor(
        hogFlowFunctionsService: HogFlowFunctionsService,
        recipientPreferencesService: RecipientPreferencesService,
        emailValidationService: EmailValidationService,
        duplicateObserver?: HogFlowDuplicateObserverService
    ) {
        this.duplicateObserver = duplicateObserver ?? null
        const hogFunctionHandler = new HogFunctionHandler(
            hogFlowFunctionsService,
            recipientPreferencesService,
            emailValidationService,
            'fetch'
        )
        const hogFunctionEmailHandler = new HogFunctionHandler(
            hogFlowFunctionsService,
            recipientPreferencesService,
            emailValidationService,
            'email'
        )

        this.actionHandlers = {
            trigger: new TriggerHandler(),
            conditional_branch: new ConditionalBranchHandler(),
            wait_until_condition: new ConditionalBranchHandler(),
            delay: new DelayHandler(),
            wait_until_time_window: new WaitUntilTimeWindowHandler(),
            random_cohort_branch: new RandomCohortBranchHandler(),
            function: hogFunctionHandler,
            function_sms: hogFunctionHandler,
            function_push: hogFunctionHandler,
            function_email: hogFunctionEmailHandler,
            exit: new ExitHandler(),
        }
    }

    async buildHogFlowInvocations(
        hogFlows: HogFlow[],
        triggerGlobals: HogFunctionInvocationGlobals
    ): Promise<{
        invocations: CyclotronJobInvocationHogFlow[]
        metrics: MinimalAppMetric[]
        logs: LogEntry[]
    }> {
        const metrics: MinimalAppMetric[] = []
        const logs: LogEntry[] = []
        const invocations: CyclotronJobInvocationHogFlow[] = []

        // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
        const filterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

        // Trigger-source compatibility is decided by the pipeline's eligibilityFn (see
        // HogFlowInvocationPipeline). Flows that reach this loop are assumed to be source-compatible
        // with the given globals — the executor's job is just to evaluate filter bytecode.
        for (const hogFlow of hogFlows) {
            const trigger = hogFlow.trigger

            // Defensive: only the trigger types that carry `filters` make it through eligibility.
            if (trigger.type !== 'event' && trigger.type !== 'data-warehouse-table') {
                continue
            }

            const filterResults = await filterFunctionInstrumented({
                fn: hogFlow,
                filters: trigger.filters,
                filterGlobals,
            })

            // Add any generated metrics and logs to our collections
            metrics.push(...filterResults.metrics)
            logs.push(...filterResults.logs)

            if (!filterResults.match) {
                continue
            }

            const invocation = createHogFlowInvocation(triggerGlobals, hogFlow, filterGlobals)
            invocations.push(invocation)
        }

        return {
            invocations,
            metrics,
            logs,
        }
    }

    private async observeDuplicateInvocation(
        invocation: CyclotronJobInvocationHogFlow,
        currentAction: HogFlowAction
    ): Promise<void> {
        await this.duplicateObserver?.observe(invocation, currentAction)
    }

    async execute(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null = null
        const metrics: MinimalAppMetric[] = []
        const logs: MinimalLogEntry[] = []
        const capturedPostHogEvents: HogFunctionCapturedEvent[] = []
        const warehouseWebhookPayloads: WarehouseWebhookPayload[] = []
        const emailAssets: MessageAssetRow[] = []

        const earlyExitResult = await this.shouldExitEarly(invocation, metrics, capturedPostHogEvents)
        if (earlyExitResult) {
            return earlyExitResult
        }

        // Routing-only reschedule: the previous dequeue moved this job onto a dedicated queue
        // (e.g. 'email' for SES rate-limit gating) and is continuing the same action. Suppress
        // the redundant trigger log — the customer-visible story should be one Resuming line
        // per real wake (delay, wait_until_condition, throttle retry), not a second one for
        // an internal queue transition. The flag stays set so executeCurrentAction can also
        // suppress its "Executing action..." debug log on this same continuation; it clears
        // the flag itself after reading so subsequent actions on this dequeue log normally.
        if (!invocation.state.currentAction?.routingOnlyReschedule) {
            logs.push(this.logExecutionTriggerInfo(invocation))
        }

        while (!result || !result.finished) {
            const nextInvocation: CyclotronJobInvocationHogFlow = result?.invocation ?? invocation

            // Here we could be continuing the hog function side of things?
            result = await this.executeCurrentAction(nextInvocation)

            if (result.finished) {
                if (result.error) {
                    this.log(result, 'error', this.logExecutionErrorInfo(result, result.error))
                } else {
                    this.log(result, 'info', `Workflow completed`)
                }

                trackE2eLag(result)
            }

            logs.push(...result.logs)
            metrics.push(...result.metrics)
            capturedPostHogEvents.push(...result.capturedPostHogEvents)
            warehouseWebhookPayloads.push(...result.warehouseWebhookPayloads)
            emailAssets.push(...result.emailAssets)

            if (this.shouldEndHogFlowExecution(result, logs)) {
                break
            }
        }

        result.logs = logs
        result.metrics = metrics
        result.capturedPostHogEvents = capturedPostHogEvents
        result.warehouseWebhookPayloads = warehouseWebhookPayloads
        result.emailAssets = emailAssets

        return result
    }

    private shouldEndHogFlowExecution(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        logs: MinimalLogEntry[]
    ): boolean {
        const finishedWithoutError = result.finished && !result.error
        const delayScheduled = Boolean(result.invocation.queueScheduledAt)

        let shouldAbortAfterError = false
        if (result.error) {
            const lastExecutedActionId = result.invocation.state.currentAction?.id
            const lastExecutedAction = result.invocation.hogFlow.actions.find((a) => a.id === lastExecutedActionId)

            if (lastExecutedAction?.on_error === 'abort') {
                shouldAbortAfterError = true
                logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `Workflow is aborting due to ${actionIdForLogging(lastExecutedAction)} error handling setting being set to abort on error`,
                })
            }
        }

        /**
         * If one of the following happens:
         * - we have finished the flow successfully
         * - something has been scheduled to run later
         * - there was an error during the action and the action's on_error is set to 'abort'
         * - we have reached the max async functions count
         *
         * then we break the loop
         */
        return finishedWithoutError || delayScheduled || shouldAbortAfterError
    }

    /**
     * Determines if the invocation should exit early based on the hogflow's exit condition
     */
    private async shouldExitEarly(
        invocation: CyclotronJobInvocationHogFlow,
        metrics: MinimalAppMetric[],
        capturedPostHogEvents: HogFunctionCapturedEvent[]
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null> {
        let earlyExitResult: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null = null

        const { hogFlow, person } = invocation
        let shouldExit = false
        let exitReason = ''

        let triggerMatch: boolean | undefined = undefined
        let conversionMatch: boolean | undefined = undefined

        if (hogFlow.trigger.type === 'event' && hogFlow.trigger.filters && person) {
            const filterResult = await filterFunctionInstrumented({
                fn: hogFlow,
                filters: hogFlow.trigger.filters,
                filterGlobals: invocation.filterGlobals,
            })
            triggerMatch = filterResult.match
        }
        if (hogFlow.conversion?.filters?.length && person) {
            if (hogFlow.conversion.bytecode?.length) {
                const filterResult = await filterFunctionInstrumented({
                    fn: hogFlow,
                    filters: {
                        bytecode: hogFlow.conversion.bytecode || [],
                        properties: hogFlow.conversion.filters || [],
                    },
                    filterGlobals: invocation.filterGlobals,
                })
                conversionMatch = filterResult.match
            } else {
                logger.error(
                    'HogFlowExecutorService: Conversion filters are set but no bytecode is provided. This means we cannot evaluate the conversion filters to determine if we should exit the flow.',
                    { hogFlowId: hogFlow.id }
                )
            }
        }
        // Count property-based conversions here, regardless of exit condition, so the metric is
        // meaningful even for flows that don't exit on conversion. Captured before the event-flag
        // override below: event-based conversions are counted by the subscription matcher, so the
        // executor must only emit for the property path or exit-on-conversion event flows double-count.
        // Guarded once-per-run by `conversionCounted` since shouldExitEarly runs on every resume.
        const propertyConversionMatched = conversionMatch === true
        let conversionMetric: MinimalAppMetric | null = null
        let conversionEvent: HogFunctionCapturedEvent | null = null
        if (propertyConversionMatched && !invocation.state.conversionCounted) {
            invocation.state.conversionCounted = true
            conversionMetric = {
                team_id: hogFlow.team_id,
                app_source_id: invocation.parentRunId ?? hogFlow.id,
                instance_id: hogFlow.id,
                metric_kind: 'other',
                metric_name: 'conversion',
                count: 1,
            }
            // Also surface the conversion as a billable PostHog event so it can power insights and
            // cohorts (mirrors the $workflows_email_* engagement events). Event-based conversions are
            // emitted by the subscription matcher, so this only fires for the property path.
            const distinctId = invocation.state.event?.distinct_id
            if (distinctId) {
                conversionEvent = {
                    team_id: hogFlow.team_id,
                    event: '$workflows_conversion',
                    distinct_id: distinctId,
                    timestamp: new Date().toISOString(),
                    properties: {
                        $workflow_id: hogFlow.id,
                        $workflow_conversion_type: 'property',
                    },
                }
            }
        }
        // Event-based conversion goals are evaluated by the subscription matcher (against the live
        // event stream), which flags the job when the conversion event fires. The property-based
        // check above can't see those, so honor the flag here. It is a one-shot signal ("the
        // conversion event just fired"), so consume it: clear it after reading so a later, unrelated
        // resume (e.g. after a subsequent delay) can't re-trigger an exit from a stale flag.
        if (invocation.state.conversionMatched) {
            conversionMatch = true
            invocation.state.conversionMatched = false
        }

        switch (hogFlow.exit_condition) {
            case 'exit_on_trigger_not_matched':
                if (triggerMatch === false) {
                    shouldExit = true
                    exitReason = `[Person:${invocation.person?.id ?? 'unknown'}|${invocation.person?.name ?? 'unknown'}] no longer matches trigger filters`
                }
                break
            case 'exit_on_conversion':
                if (conversionMatch === true) {
                    shouldExit = true
                    exitReason = `[Person:${invocation.person?.id ?? 'unknown'}|${invocation.person?.name ?? 'unknown'}] matches conversion filters`
                }
                break
            case 'exit_on_trigger_not_matched_or_conversion':
                if (triggerMatch === false || conversionMatch === true) {
                    shouldExit = true
                    exitReason =
                        triggerMatch === false
                            ? `[Person:${invocation.person?.id ?? 'unknown'}|${invocation.person?.name ?? 'unknown'}] no longer matches trigger filters`
                            : `[Person:${invocation.person?.id ?? 'unknown'}|${invocation.person?.name ?? 'unknown'}] matches conversion filters`
                }
                break
        }

        if (shouldExit) {
            earlyExitResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation)
            earlyExitResult.finished = true
            earlyExitResult.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Workflow exited early due to exit condition: ${hogFlow.exit_condition} (${exitReason})`,
            })
            earlyExitResult.metrics.push({
                team_id: hogFlow.team_id,
                app_source_id: invocation.parentRunId ?? hogFlow.id,
                instance_id: invocation.state?.currentAction?.id || 'exit_condition',
                metric_kind: 'other',
                metric_name: 'early_exit',
                count: 1,
            })
        }

        // Route the conversion metric/event onto whichever result is actually flushed: the early-exit
        // result when we exit, otherwise the caller's arrays (which become result.metrics /
        // result.capturedPostHogEvents once the run continues and finishes).
        if (conversionMetric) {
            ;(earlyExitResult?.metrics ?? metrics).push(conversionMetric)
        }
        if (conversionEvent) {
            ;(earlyExitResult?.capturedPostHogEvents ?? capturedPostHogEvents).push(conversionEvent)
        }

        return earlyExitResult
    }

    public async executeCurrentAction(
        invocation: CyclotronJobInvocationHogFlow,
        options?: {
            hogExecutorOptions?: HogExecutorExecuteAsyncOptions
        }
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        const result = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation)
        result.finished = false // Typically we are never finished unless we error or exit

        try {
            const currentAction = ensureCurrentAction(invocation)

            if (await shouldSkipAction(invocation, currentAction)) {
                this.logAction(result, currentAction, 'info', `Skipped due to filter conditions`)
                this.goToNextAction(result, currentAction, findContinueAction(invocation), 'filtered')

                return result
            }

            await this.observeDuplicateInvocation(invocation, currentAction)

            // Routing-only reschedule continuation (see hog_function.ts): the previous dequeue
            // set this flag so the executor knows the current call is just resuming an action
            // that was momentarily parked to switch queues — not the start of a fresh action
            // step. Suppress the redundant "Executing action..." log and consume the flag so
            // subsequent actions (next handler returns nextAction → loop continues) log normally.
            if (invocation.state.currentAction?.routingOnlyReschedule) {
                invocation.state.currentAction.routingOnlyReschedule = false
            } else {
                result.logs.push({
                    level: 'debug',
                    message: `Executing action ${actionIdForLogging(currentAction)}`,
                    timestamp: DateTime.now(),
                })
            }
            logger.debug('🦔', `[HogFlowActionRunner] Running action ${currentAction.type}`, {
                action: currentAction,
                invocation,
            })

            const handler = this.actionHandlers[currentAction.type]
            if (!handler) {
                throw new Error(`Action type '${currentAction.type}' not supported`)
            }

            try {
                const handlerResult = await handler.execute({
                    invocation,
                    action: currentAction,
                    result,
                    hogExecutorOptions: options?.hogExecutorOptions,
                })

                if (handlerResult.error) {
                    throw handlerResult.error instanceof Error ? handlerResult.error : new Error(handlerResult.error)
                }

                if (handlerResult.result) {
                    this.trackActionResult(result, currentAction, handlerResult.result)
                    result.execResult = handlerResult.result
                }

                if (handlerResult.finished) {
                    result.finished = true
                    // Special case for exit - we just track a success metric
                    this.trackActionMetric(result, currentAction, 'succeeded')
                }

                if (handlerResult.scheduledAt) {
                    this.scheduleInvocation(result, handlerResult.scheduledAt)
                }

                if (handlerResult.nextAction) {
                    this.goToNextAction(result, currentAction, handlerResult.nextAction, 'succeeded')
                }
            } catch (err) {
                // Add logs and metric specifically for this action
                this.logAction(result, currentAction, 'error', `Errored: ${String(err)}`) // TODO: Is this enough detail?
                this.trackActionMetric(result, currentAction, 'failed')

                throw err
            }
        } catch (err) {
            // The final catch - in this case we are always just logging the final outcome
            result.error = err.message
            result.finished = true // Explicitly set to true to prevent infinite loops

            this.maybeContinueToNextActionOnError(result)

            logger.error(
                '🦔',
                `[HogFlowExecutor] Error executing hog flow ${invocation.hogFlow.id} - ${invocation.hogFlow.name}. Event: '${invocation.state.event?.url}'`,
                err
            )
        }

        return result
    }

    private goToNextAction(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        currentAction: HogFlowAction,
        nextAction: HogFlowAction,
        reason: 'filtered' | 'failed' | 'succeeded'
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> {
        result.finished = false

        result.invocation.state.actionStepCount++
        // Update the state to be going to the next action
        result.invocation.state.currentAction = {
            id: nextAction.id,
            startedAtTimestamp: DateTime.now().toMillis(),
        }

        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Workflow moved to action ${actionIdForLogging(nextAction)}`,
        })

        this.trackActionMetric(result, currentAction, reason)

        return result
    }

    /**
     * If the action has on_error set to 'continue' then we continue to the next action instead of failing the flow
     */
    private maybeContinueToNextActionOnError(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    ): void {
        try {
            const { invocation } = result
            // If current action's on_error is set to 'continue', we move to the next action instead of failing the flow
            const currentAction = ensureCurrentAction(invocation)
            if (currentAction?.on_error === 'continue') {
                const nextAction = findContinueAction(invocation)
                if (nextAction) {
                    this.logAction(
                        result,
                        currentAction,
                        'info',
                        `Continuing to next action ${actionIdForLogging(nextAction)} despite error due to error handling setting being set to continue on error`
                    )

                    /**
                     * TODO: Determine if we should track this as a 'succeeded' metric here or
                     * a new metric_name e.g. 'continued_after_error'
                     */
                    this.goToNextAction(result, currentAction, nextAction, 'succeeded')
                }
            }
        } catch (err) {
            logger.error('Error trying to continue to next action on error', { error: err })
        }
    }

    /**
     * Updates the scheduledAt field on the result to indicate that the invocation should be scheduled for the future
     */
    private scheduleInvocation(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        scheduledAt: DateTime
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> {
        // If the result has scheduled for the future then we return that triggering a push back to the queue
        result.invocation.queueScheduledAt = scheduledAt
        result.finished = false
        // Routing-only reschedules (hog function moving the job onto a dedicated queue) don't
        // represent a workflow-author-visible pause — the next dequeue fires almost
        // immediately and continues the same action. Skip the "Workflow will pause until..."
        // log in that case so it doesn't surface as a pause the workflow never actually took.
        // Real pauses (delays, wait_until_condition, throttle retries) still log normally.
        if (!result.invocation.state.currentAction?.routingOnlyReschedule) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Workflow will pause until ${scheduledAt.toUTC().toISO()}`,
            })
        }

        return result
    }

    private logAction(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        action: HogFlowAction,
        level: LogEntryLevel,
        message: string
    ): void {
        this.log(result, level, `${actionIdForLogging(action)} ${message}`)
    }

    private log(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        level: LogEntryLevel,
        message: string
    ): void {
        result.logs.push({
            level,
            timestamp: DateTime.now(),
            message,
        })
    }

    private trackActionMetric(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        action: HogFlowAction,
        metricName: 'failed' | 'succeeded' | 'filtered'
    ): void {
        result.metrics.push({
            team_id: result.invocation.hogFlow.team_id,
            app_source_id: result.invocation.parentRunId ?? result.invocation.hogFlow.id,
            instance_id: action.id,
            metric_kind: metricName === 'failed' ? 'failure' : metricName === 'succeeded' ? 'success' : 'other',
            metric_name: metricName,
            count: 1,
        })
    }

    private trackActionResult(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        action: HogFlowAction,
        actionResult: unknown
    ): void {
        // Normalize output_variable to an array for uniform handling
        const outputVars = Array.isArray(action.output_variable)
            ? action.output_variable
            : action.output_variable
              ? [action.output_variable]
              : []

        if (outputVars.length === 0) {
            return
        }

        if (!actionResult) {
            this.log(
                result,
                'warn',
                `An output variable was specified for [Action:${action.id}], but no output was returned.`
            )
            return
        }

        if (!result.invocation.state.variables) {
            result.invocation.state.variables = {}
        }

        const allStoredKeys: string[] = []

        for (const outputVar of outputVars) {
            if (!outputVar.key) {
                continue
            }

            const resolvedResult = outputVar.result_path ? get(actionResult, outputVar.result_path) : actionResult

            // When spread is true, store each property of the result as a separate variable
            if (
                outputVar.spread &&
                typeof resolvedResult === 'object' &&
                resolvedResult !== null &&
                !Array.isArray(resolvedResult)
            ) {
                const prefix = outputVar.key
                for (const [prop, value] of Object.entries(resolvedResult)) {
                    const spreadKey = `${prefix}_${prop}`
                    result.invocation.state.variables[spreadKey] = value
                    allStoredKeys.push(spreadKey)
                }
            } else {
                result.invocation.state.variables[outputVar.key] = resolvedResult
                allStoredKeys.push(outputVar.key)
            }
        }

        // Check that total variables are below 5KB
        const resultSize = Buffer.byteLength(JSON.stringify(result.invocation.state.variables), 'utf8')
        if (resultSize > 5120) {
            const keyNames = allStoredKeys.join(', ')
            this.log(
                result,
                'error',
                `Total variable size after updating '${keyNames}' exceeds 5KB limit. Use result_path to store only the fields you need.`
            )
            // Clean up all variables we just set
            for (const key of allStoredKeys) {
                delete result.invocation.state.variables[key]
            }
            throw new Error(
                `Total variable size after updating '${keyNames}' exceeds 5KB limit. Use result_path to store only the fields you need.`
            )
        }

        const storedSummary = allStoredKeys
            .map((key) => `${key} = ${JSON.stringify(result.invocation.state.variables![key])}`)
            .join(', ')
        this.log(result, 'debug', `Stored action result in variable(s): ${storedSummary}`)
    }

    private logExecutionTriggerInfo(invocation: CyclotronJobInvocationHogFlow): MinimalLogEntry {
        const hasCurrentAction = Boolean(invocation.state.currentAction)
        const currentAction = hasCurrentAction ? `[Action:${invocation.state.currentAction!.id}]` : 'trigger'

        const hasAssociatedPerson = Boolean(invocation.person)
        const hasAssociatedEvent = Boolean(invocation.state.event)
        const isWebhookTriggered = ['webhook', 'manual', 'schedule'].includes(invocation.hogFlow.trigger.type)
        const isBatchWorkflow = invocation.hogFlow.trigger.type === 'batch'

        let triggeredForActor = ''
        if (!hasCurrentAction) {
            triggeredForActor = isWebhookTriggered
                ? ` at request of [Actor:${invocation.state.event?.distinct_id ?? 'unknown'}]`
                : ''
            triggeredForActor += hasAssociatedPerson
                ? ` for [Person:${invocation.person?.id}|${invocation.person?.name ?? 'unknown'}]`
                : ''
        }

        let triggeredByEvent = hasAssociatedEvent
            ? ` on [Event:${invocation.state.event?.uuid}|${invocation.state.event?.event?.replaceAll('|', '')}|${invocation.state.event?.timestamp}]`
            : ''

        // Surface the event that woke the job (not the trigger). The logs view builds the link
        // from uuid + timestamp, so emit the linkable token only when both are present.
        const wakeEvent = invocation.state.currentAction?.eventMatchedEvent
        const wakeEventUuid = invocation.state.currentAction?.eventMatchedEventUuid
        const wakeEventTimestamp = invocation.state.currentAction?.eventMatchedEventTimestamp
        if (hasCurrentAction && invocation.state.currentAction?.eventMatched && wakeEvent) {
            triggeredByEvent +=
                wakeEventUuid && wakeEventTimestamp
                    ? ` (woken by [Event:${wakeEventUuid}|${wakeEvent.replaceAll('|', '')}|${wakeEventTimestamp}])`
                    : ` (woken by event: ${wakeEvent.replaceAll('|', '')})`
        }

        return {
            level: 'info',
            message: `${hasCurrentAction ? 'Resuming' : 'Starting'} ${isBatchWorkflow ? 'batch ' : ''}workflow execution at ${currentAction}${triggeredForActor}${triggeredByEvent}`,
            timestamp: DateTime.now(),
        }
    }

    private logExecutionErrorInfo(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        error: Error
    ): string {
        const invocation = result.invocation
        const currentActionId = invocation.state.currentAction?.id
        const currentAction = currentActionId ? invocation.hogFlow.actions.find((a) => a.id === currentActionId) : null

        const hasAssociatedEvent = Boolean(invocation.state.event)
        const triggeredByEvent = hasAssociatedEvent
            ? `. This workflow was triggered by [Event:${invocation.state.event?.uuid}|${invocation.state.event?.event?.replaceAll('|', '')}|${invocation.state.event?.timestamp}]`
            : ''

        return `Workflow encountered an error: ${error.message} at ${currentAction ? actionIdForLogging(currentAction) : 'unknown action'}${triggeredByEvent}`
    }
}
