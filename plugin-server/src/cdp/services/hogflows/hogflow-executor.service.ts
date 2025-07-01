import { DateTime } from 'luxon'

import { HogFlow, HogFlowAction } from '../../../schema/hogflow'
import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'
import { UUIDT } from '../../../utils/utils'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    LogEntry,
    LogEntryLevel,
    MinimalAppMetric,
    MinimalLogEntry,
} from '../../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../../utils/hog-function-filtering'
import { createInvocationResult } from '../../utils/invocation-utils'
import { buildGlobalsWithInputs, HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { checkConditions } from './actions/conditional_branch'
import { calculatedScheduledAt } from './actions/delay'
import { getRandomCohort } from './actions/random_cohort_branch'
import { getWaitUntilTime } from './actions/wait_until_time_window'
import { findContinueAction } from './hogflow-utils'
import { ensureCurrentAction, shouldSkipAction } from './hogflow-utils'

export const MAX_ACTION_STEPS_HARD_LIMIT = 1000

export function createHogFlowInvocation(
    globals: HogFunctionInvocationGlobals,
    hogFlow: HogFlow
): CyclotronJobInvocationHogFlow {
    return {
        id: new UUIDT().toString(),
        state: {
            personId: globals.person?.id ?? '',
            event: globals.event,
            actionStepCount: 0,
        },
        teamId: hogFlow.team_id,
        functionId: hogFlow.id, // TODO: Include version?
        hogFlow,
        queue: 'hogflow',
        queuePriority: 1,
    }
}

export class HogFlowExecutorService {
    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService
    ) {}

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

            const invocation = createHogFlowInvocation(triggerGlobals, hogFlow)
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

            try {
                switch (currentAction.type) {
                    case 'conditional_branch':
                        const conditionResult = await checkConditions(invocation, currentAction)

                        if (conditionResult.scheduledAt) {
                            this.scheduleInvocation(result, conditionResult.scheduledAt)
                        } else if (conditionResult.nextAction) {
                            this.goToNextAction(result, currentAction, conditionResult.nextAction, 'succeeded')
                        }

                        break
                    case 'delay':
                        const scheduledAt = calculatedScheduledAt(
                            currentAction.config.delay_duration,
                            invocation.state.currentAction?.startedAtTimestamp
                        )

                        // Move to the next action regardless
                        this.goToNextAction(result, currentAction, findContinueAction(invocation), 'succeeded')

                        if (scheduledAt) {
                            // Schedule it if we have a delay
                            this.scheduleInvocation(result, scheduledAt)
                        }

                        break
                    case 'wait_until_condition':
                        const waitUntilConditionResult = await checkConditions(invocation, {
                            ...currentAction,
                            type: 'conditional_branch',
                            config: {
                                conditions: [currentAction.config.condition],
                                delay_duration: currentAction.config.max_wait_duration,
                            },
                        })

                        if (waitUntilConditionResult.scheduledAt) {
                            this.scheduleInvocation(result, waitUntilConditionResult.scheduledAt)
                        } else if (waitUntilConditionResult.nextAction) {
                            this.goToNextAction(result, currentAction, waitUntilConditionResult.nextAction, 'succeeded')
                        }

                        break
                    case 'wait_until_time_window':
                        const nextTime = getWaitUntilTime(currentAction)
                        if (nextTime) {
                            this.scheduleInvocation(result, nextTime)
                        }
                        this.goToNextAction(result, currentAction, findContinueAction(invocation), 'succeeded')
                        break
                    case 'random_cohort_branch':
                        const nextActionFromRandomCohort = getRandomCohort(invocation, currentAction)
                        this.goToNextAction(result, currentAction, nextActionFromRandomCohort, 'succeeded')
                        break

                    case 'function':
                        const functionResult = await this.executeHogFunction(invocation, currentAction)

                        // Add all logs
                        functionResult.logs.forEach((log) => {
                            result.logs.push({
                                level: log.level,
                                timestamp: log.timestamp,
                                message: `[Action:${currentAction.id}] ${log.message}`,
                            })
                        })

                        if (!functionResult.finished) {
                            this.scheduleInvocation(
                                result,
                                functionResult.invocation.queueScheduledAt ?? DateTime.now()
                            )
                        } else {
                            this.goToNextAction(result, currentAction, findContinueAction(invocation), 'succeeded')
                        }

                        break
                    case 'exit':
                        // Exit is the simplest case
                        result.finished = true
                        this.log(result, 'info', `Workflow completed`)
                        this.trackActionMetric(result, currentAction, 'success', 'succeeded')
                        return result
                    default:
                        throw new Error(`Action type '${currentAction.type}' not supported`)
                }
            } catch (err) {
                // Add logs and metric specifically for this action
                this.logAction(result, currentAction, 'error', `Errored: ${String(err)}`) // TODO: Is this enough detail?
                this.trackActionMetric(result, currentAction, 'failure', 'failed')

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

        this.trackActionMetric(
            result,
            currentAction,
            reason === 'filtered' ? 'other' : 'success',
            reason === 'filtered' ? 'filtered' : 'succeeded'
        )

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
            message: `Workflow will pause until ${scheduledAt.toISO()}`,
        })

        return result
    }

    private trackActionMetric(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        action: HogFlowAction,
        metricKind: 'failure' | 'success' | 'other',
        metricName: 'failed' | 'succeeded' | 'filtered'
    ): void {
        result.metrics.push({
            team_id: result.invocation.hogFlow.team_id,
            app_source_id: result.invocation.hogFlow.id,
            instance_id: action.id,
            metric_kind: metricKind,
            metric_name: metricName,
            count: 1,
        })
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

    private async executeHogFunction(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'function' }>
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        // Executing a hog function involves a few steps
        // 1. Finding the template to use
        // 2. Building the globals
        // 3. Executing the hog function
        // 4. Returning the result

        // TODO: Get the existing state from the invocation

        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(action.config.template_id)

        if (!template) {
            throw new Error(`Template '${action.config.template_id}' not found`)
        }

        const hogFunction: HogFunctionType = {
            id: invocation.hogFlow.id, // We use the hog function flow ID
            team_id: invocation.teamId,
            name: `${invocation.hogFlow.name} - ${template.name}`,
            enabled: true,
            type: 'destination',
            deleted: false,
            hog: '<<TEMPLATE>>',
            bytecode: template.bytecode,
            is_addon_required: false,
            created_at: '',
            updated_at: '',
        }

        const teamId = invocation.hogFlow.team_id
        const projectUrl = `${this.hub.SITE_URL}/project/${teamId}`

        const globals: HogFunctionInvocationGlobals = {
            source: {
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${projectUrl}/functions/${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
            event: invocation.state.event,
            // TODO: Add person info
        }

        // TODO: Load the state information out of the hog flow invocation
        // to be passed in potentially
        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: {
                globals: await buildGlobalsWithInputs(globals, action.config.inputs),
                timings: [],
                attempts: 0,
            },
        }

        const result = await this.hogFunctionExecutor.executeWithAsyncFunctions(hogFunctionInvocation)

        return result
    }
}
