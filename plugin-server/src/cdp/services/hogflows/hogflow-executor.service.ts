import { DateTime } from 'luxon'

import { HogFlow, HogFlowAction } from '../../../schema/hogflow'
import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'
import { UUIDT } from '../../../utils/utils'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    LogEntry,
    LogEntryLevel,
    MinimalAppMetric,
    MinimalLogEntry,
} from '../../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../../utils/hog-function-filtering'
import { createInvocationResult } from '../../utils/invocation-utils'
import { HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { ActionHandler } from './actions/action.interface'
import { ConditionalBranchHandler } from './actions/conditional_branch'
import { DelayHandler } from './actions/delay'
import { ExitHandler } from './actions/exit.handler'
import { HogFunctionHandler } from './actions/hog_function'
import { RandomCohortBranchHandler } from './actions/random_cohort_branch'
import { TriggerHandler } from './actions/trigger.handler'
import { WaitUntilTimeWindowHandler } from './actions/wait_until_time_window'
import { actionIdForLogging, ensureCurrentAction, findContinueAction, shouldSkipAction } from './hogflow-utils'

export const MAX_ACTION_STEPS_HARD_LIMIT = 1000

export class HogFlowExecutorService {
    private readonly actionHandlers: Record<HogFlowAction['type'], ActionHandler>

    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService,
        private recipientPreferencesService: RecipientPreferencesService
    ) {
        const hogFunctionHandler = new HogFunctionHandler(
            this.hub,
            this.hogFunctionExecutor,
            this.hogFunctionTemplateManager,
            this.recipientPreferencesService
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
            function_email: hogFunctionHandler,
            exit: new ExitHandler(),
        }
    }

    public createHogFlowInvocation(
        globals: HogFunctionInvocationGlobals,
        hogFlow: HogFlow,
        filterGlobals: HogFunctionFilterGlobals
    ): CyclotronJobInvocationHogFlow {
        return {
            id: new UUIDT().toString(),
            state: {
                event: globals.event,
                actionStepCount: 0,
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

            const invocation = this.createHogFlowInvocation(triggerGlobals, hogFlow, filterGlobals)
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

        const earlyExitResult = await this.shouldExitEarly(invocation)
        if (earlyExitResult) {
            return earlyExitResult
        }

        while (!result || !result.finished) {
            const nextInvocation: CyclotronJobInvocationHogFlow = result?.invocation ?? invocation

            // Here we could be continuing the hog function side of things?
            result = await this.executeCurrentAction(nextInvocation)

            if (result.finished) {
                this.log(result, 'info', `Workflow completed`)
            }

            logs.push(...result.logs)
            metrics.push(...result.metrics)

            // If we have finished _or_ something has been scheduled to run later _or_ we have reached the max async functions then we break the loop
            if (result.finished || result.invocation.queueScheduledAt) {
                break
            }
        }

        result.logs = logs
        result.metrics = metrics

        return result
    }

    /**
     * Determines if the invocation should exit early based on the hogflow's exit condition
     */
    private async shouldExitEarly(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null> {
        let earlyExitResult: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null = null

        // Respect exit_condition before executing actions
        const { hogFlow, person } = invocation
        let shouldExit = false
        let exitReason = ''

        // Always evaluate both filter matches up front using filterFunctionInstrumented
        let triggerMatch: boolean | undefined = undefined
        let conversionMatch: boolean | undefined = undefined

        // Use the same filter evaluation as in buildHogFlowInvocations
        if (hogFlow.trigger.filters && person) {
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
        invocation: CyclotronJobInvocationHogFlow
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

            logger.debug('🦔', `[HogFlowActionRunner] Running action ${currentAction.type}`, {
                action: currentAction,
                invocation,
            })

            const handler = this.actionHandlers[currentAction.type]
            if (!handler) {
                throw new Error(`Action type '${currentAction.type}' not supported`)
            }

            try {
                const handlerResult = await handler.execute(invocation, currentAction, result)

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
        reason: 'filtered' | 'succeeded'
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

        this.trackActionMetric(result, currentAction, reason === 'filtered' ? 'filtered' : 'succeeded')

        return result
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
}
