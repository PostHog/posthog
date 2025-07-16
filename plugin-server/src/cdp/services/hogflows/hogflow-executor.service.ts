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
import { ActionHandler } from './actions/action.interface'
import { ConditionalBranchHandler } from './actions/conditional_branch'
import { DelayHandler } from './actions/delay'
import { ExitHandler } from './actions/exit.handler'
import { HogFunctionHandler } from './actions/hog_function'
import { RandomCohortBranchHandler } from './actions/random_cohort_branch'
import { WaitUntilTimeWindowHandler } from './actions/wait_until_time_window'
import { findContinueAction } from './hogflow-utils'
import { ensureCurrentAction, shouldSkipAction } from './hogflow-utils'

export const MAX_ACTION_STEPS_HARD_LIMIT = 1000

export class HogFlowExecutorService {
    private readonly actionHandlers: Map<string, ActionHandler>

    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService
    ) {
        this.actionHandlers = this.initializeActionHandlers()
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

    private initializeActionHandlers(): Map<HogFlowAction['type'], ActionHandler> {
        const handlers = new Map<HogFlowAction['type'], ActionHandler>()
        handlers.set('conditional_branch', new ConditionalBranchHandler())
        handlers.set('wait_until_condition', new ConditionalBranchHandler())
        handlers.set('delay', new DelayHandler())
        handlers.set('wait_until_time_window', new WaitUntilTimeWindowHandler())
        handlers.set('random_cohort_branch', new RandomCohortBranchHandler())

        const hogFunctionHandler = new HogFunctionHandler(
            this.hub,
            this.hogFunctionExecutor,
            this.hogFunctionTemplateManager
        )
        handlers.set('function', hogFunctionHandler)
        handlers.set('function_sms', hogFunctionHandler)
        handlers.set('function_slack', hogFunctionHandler)
        handlers.set('function_email', hogFunctionHandler)
        handlers.set('function_webhook', hogFunctionHandler)

        handlers.set('exit', new ExitHandler())
        return handlers
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
                eventUuid: triggerGlobals.event.uuid,
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

    // Like execute but does the complete flow, logging delays and async function calls rather than performing them
    async executeTest(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        const finalResult = createInvocationResult<CyclotronJobInvocationHogFlow>(
            invocation,
            {},
            {
                finished: false,
            }
        )

        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null = null

        let loopCount = 0

        while (!result || !result.finished) {
            logger.info('🦔', `[HogFlowExecutor] Executing hog flow invocation`, {
                loopCount,
            })
            loopCount++
            if (loopCount > 100) {
                // NOTE: This is hardcoded for now to prevent infinite loops. Later we should fix this properly.
                break
            }

            const nextInvocation: CyclotronJobInvocationHogFlow = result?.invocation ?? invocation

            result = await this.execute(nextInvocation)

            if (result?.invocation.queueScheduledAt) {
                this.log(finalResult, 'info', `Workflow will pause until ${result.invocation.queueScheduledAt.toISO()}`)
            }

            result?.logs?.forEach((log) => {
                finalResult.logs.push(log)
            })
            result?.metrics?.forEach((metric) => {
                finalResult.metrics.push(metric)
            })
        }

        return finalResult
    }

    private async executeCurrentAction(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        const result = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation)
        result.finished = false // Typically we are never finished unless we error or exit

        try {
            const currentAction = ensureCurrentAction(invocation)

            // TODO: Add early condition for continuing a hog function
            if (await shouldSkipAction(invocation, currentAction)) {
                this.logAction(result, currentAction, 'info', `Skipped due to filter conditions`)
                this.goToNextAction(result, currentAction, findContinueAction(invocation), 'filtered')

                return result
            }

            logger.debug('🦔', `[HogFlowActionRunner] Running action ${currentAction.type}`, {
                action: currentAction,
                invocation,
            })

            const handler = this.actionHandlers.get(currentAction.type)
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
            message: `Workflow moved to action '${nextAction.name} (${nextAction.id})'`,
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
        this.log(result, level, `[Action:${action.id}] ${message}`)
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
