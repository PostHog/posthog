import { get } from 'lodash'
import { DateTime } from 'luxon'

import { HogFlow, HogFlowAction } from '../../../schema/hogflow'
import { logger } from '../../../utils/logger'
import { UUIDT } from '../../../utils/utils'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFunctionCapturedEvent,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    LogEntry,
    LogEntryLevel,
    MinimalAppMetric,
    MinimalLogEntry,
} from '../../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../../utils/hog-function-filtering'
import { createInvocationResult } from '../../utils/invocation-utils'
import { HogExecutorExecuteAsyncOptions } from '../hog-executor.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { ActionHandler } from './actions/action.interface'
import { ConditionalBranchHandler } from './actions/conditional_branch'
import { DelayHandler } from './actions/delay'
import { ExitHandler } from './actions/exit.handler'
import { HogFunctionHandler } from './actions/hog_function'
import { RandomCohortBranchHandler } from './actions/random_cohort_branch'
import { TriggerHandler } from './actions/trigger.handler'
import { WaitUntilTimeWindowHandler } from './actions/wait_until_time_window'
import { HogFlowFunctionsService } from './hogflow-functions.service'
import { actionIdForLogging, ensureCurrentAction, findContinueAction, shouldSkipAction } from './hogflow-utils'

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
        filterGlobals,
        queue: 'hogflow',
        queuePriority: 1,
    }
}

export class HogFlowExecutorService {
    private readonly actionHandlers: Record<HogFlowAction['type'], ActionHandler>

    constructor(
        hogFlowFunctionsService: HogFlowFunctionsService,
        recipientPreferencesService: RecipientPreferencesService
    ) {
        const hogFunctionHandler = new HogFunctionHandler(hogFlowFunctionsService, recipientPreferencesService)

        this.actionHandlers = {
            trigger: new TriggerHandler(),
            conditional_branch: new ConditionalBranchHandler(),
            wait_until_condition: new ConditionalBranchHandler(),
            delay: new DelayHandler(),
            wait_until_time_window: new WaitUntilTimeWindowHandler(),
            random_cohort_branch: new RandomCohortBranchHandler(),
            function: hogFunctionHandler,
            function_sms: hogFunctionHandler,
            function_email: hogFunctionHandler,
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

        for (const hogFlow of hogFlows) {
            if (hogFlow.trigger.type !== 'event') {
                continue
            }
            const filterResults = await filterFunctionInstrumented({
                fn: hogFlow,
                filters: hogFlow.trigger.filters,
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

    async execute(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null = null
        const metrics: MinimalAppMetric[] = []
        const logs: MinimalLogEntry[] = []
        const capturedPostHogEvents: HogFunctionCapturedEvent[] = []

        const earlyExitResult = await this.shouldExitEarly(invocation)
        if (earlyExitResult) {
            return earlyExitResult
        }

        const hasCurrentAction = Boolean(invocation.state.currentAction)
        const currentAction = hasCurrentAction ? `[Action:${invocation.state.currentAction!.id}]` : 'trigger'
        logs.push({
            level: 'debug',
            message: `${hasCurrentAction ? 'Resuming' : 'Starting'} workflow execution at ${currentAction}`,
            timestamp: DateTime.now(),
        })

        while (!result || !result.finished) {
            const nextInvocation: CyclotronJobInvocationHogFlow = result?.invocation ?? invocation

            // Here we could be continuing the hog function side of things?
            result = await this.executeCurrentAction(nextInvocation)

            if (result.finished) {
                if (result.error) {
                    this.log(result, 'error', `Workflow encountered an error: ${result.error}`)
                } else {
                    this.log(result, 'info', `Workflow completed`)
                }
            }

            logs.push(...result.logs)
            metrics.push(...result.metrics)
            capturedPostHogEvents.push(...result.capturedPostHogEvents)

            if (this.shouldEndHogFlowExecution(result, logs)) {
                break
            }
        }

        result.logs = logs
        result.metrics = metrics
        result.capturedPostHogEvents = capturedPostHogEvents

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
                    message: `Workflow is aborting due to the action's error handling setting (on_error: 'abort')`,
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
        invocation: CyclotronJobInvocationHogFlow
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
        if (hogFlow.conversion?.filters && person) {
            const filterResult = await filterFunctionInstrumented({
                fn: hogFlow,
                filters: hogFlow.conversion.filters,
                filterGlobals: invocation.filterGlobals,
            })
            conversionMatch = filterResult.match
        }

        switch (hogFlow.exit_condition) {
            case 'exit_on_trigger_not_matched':
                if (triggerMatch === false) {
                    shouldExit = true
                    exitReason = 'Person no longer matches trigger filters'
                }
                break
            case 'exit_on_conversion':
                if (conversionMatch === true) {
                    shouldExit = true
                    exitReason = 'Person matches conversion filters'
                }
                break
            case 'exit_on_trigger_not_matched_or_conversion':
                if (triggerMatch === false || conversionMatch === true) {
                    shouldExit = true
                    exitReason =
                        triggerMatch === false
                            ? 'Person no longer matches trigger filters'
                            : 'Person matches conversion filters'
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
                app_source_id: hogFlow.id,
                instance_id: invocation.state?.currentAction?.id || 'exit_condition',
                metric_kind: 'other',
                metric_name: 'early_exit',
                count: 1,
            })
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

            result.logs.push({
                level: 'debug',
                message: `Executing action ${actionIdForLogging(currentAction)}`,
                timestamp: DateTime.now(),
            })
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

                if (handlerResult.result) {
                    this.trackActionResult(result, currentAction, handlerResult.result)
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
                        `Continuing to next action ${actionIdForLogging(nextAction)} despite error due to on_error setting`
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
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Workflow will pause until ${scheduledAt.toUTC().toISO()}`,
        })

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
            app_source_id: result.invocation.hogFlow.id,
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
        if (action.output_variable?.key) {
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

            result.invocation.state.variables[action.output_variable.key] = action.output_variable?.result_path
                ? get(actionResult, action.output_variable.result_path)
                : actionResult

            // Check that result to be stored is below 1kb
            const resultSize = Buffer.byteLength(JSON.stringify(result.invocation.state.variables), 'utf8')
            if (resultSize > 1024) {
                this.log(
                    result,
                    'warn',
                    `Total variable size after updating '${action.output_variable.key}' is larger than 1KB, this result will not be stored and won't be available in subsequent actions.`
                )
                delete result.invocation.state.variables[action.output_variable.key]
                return
            }

            this.log(
                result,
                'debug',
                `Stored action result in variable '${action.output_variable.key}': ${JSON.stringify(result.invocation.state.variables[action.output_variable.key])}`
            )
        }
    }
}
