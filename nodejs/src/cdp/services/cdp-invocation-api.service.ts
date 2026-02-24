import { DateTime } from 'luxon'

import { ModifiedRequest } from '~/api/router'
import { PluginEvent } from '~/plugin-scaffold'

import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { UUID, UUIDT } from '../../utils/utils'
import { getAsyncFunctionHandler, getRegisteredAsyncFunctionNames } from '../async-function-registry'
import '../async-functions'
import { HogTransformerService } from '../hog-transformations/hog-transformer.service'
import { HogFunctionInvocationGlobals, HogFunctionType, MinimalLogEntry } from '../types'
import { convertToHogFunctionInvocationGlobals, isNativeHogFunction, isSegmentPluginHogFunction } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { HogExecutorExecuteAsyncOptions, HogExecutorService, MAX_ASYNC_STEPS } from './hog-executor.service'
import { HogFlowExecutorService, createHogFlowInvocation } from './hogflows/hogflow-executor.service'
import { HogFlowManagerService } from './hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from './managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { NativeDestinationExecutorService } from './native-destination-executor.service'
import { SegmentDestinationExecutorService } from './segment-destination-executor.service'

export class CdpInvocationError extends Error {
    constructor(
        message: string,
        public readonly statusCode: number
    ) {
        super(message)
        this.name = 'CdpInvocationError'
    }
}

export type TestFunctionResult = {
    result: any
    status: 'success' | 'error' | 'skipped'
    errors: string[]
    logs: MinimalLogEntry[]
}

export type TestFlowResult = {
    nextActionId: string | undefined
    status: 'success' | 'error'
    errors: string[]
    logs: MinimalLogEntry[]
    variables: Record<string, any>
    execResult: any
}

export class CdpInvocationAPIService {
    constructor(
        private hub: Pick<Hub, 'teamManager' | 'SITE_URL'>,
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private hogExecutor: HogExecutorService,
        private hogFlowExecutor: HogFlowExecutorService,
        private nativeDestinationExecutorService: NativeDestinationExecutorService,
        private segmentDestinationExecutorService: SegmentDestinationExecutorService,
        private hogTransformer: HogTransformerService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService
    ) {}

    async testHogFunctionInvocation(req: ModifiedRequest): Promise<TestFunctionResult> {
        const { id, team_id } = req.params
        const { clickhouse_event, mock_async_functions, configuration, invocation_id } = req.body

        logger.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

        const invocationID = invocation_id ?? new UUIDT().toString()

        if (!UUID.validateString(invocationID)) {
            throw new CdpInvocationError('Invalid invocation ID', 400)
        }

        const isNewFunction = id === 'new'

        const hogFunction = isNewFunction ? null : await this.hogFunctionManager.fetchHogFunction(id).catch(() => null)
        const team = await this.hub.teamManager.getTeam(parseInt(team_id)).catch(() => null)

        if (!team) {
            throw new CdpInvocationError('Team not found', 404)
        }

        const globals = clickhouse_event
            ? convertToHogFunctionInvocationGlobals(clickhouse_event, team, this.hub.SITE_URL)
            : req.body.globals

        if (!globals || !globals.event) {
            throw new CdpInvocationError('Missing event', 400)
        }

        // The real security happens at the django layer so this is more of a sanity check
        if (!isNewFunction && (!hogFunction || hogFunction.team_id !== team.id)) {
            throw new CdpInvocationError('Hog function not found', 404)
        }

        const compoundConfiguration = {
            ...hogFunction,
            ...configuration,
            team_id: team.id,
        } as HogFunctionType

        let logs: MinimalLogEntry[] = []
        let result: any = null
        const errors: any[] = []

        const defaultProject = {
            id: team.id,
            name: team.name,
            url: `${this.hub.SITE_URL}/project/${team.id}`,
        }
        const triggerGlobals: HogFunctionInvocationGlobals = {
            ...globals,
            project: {
                ...defaultProject,
                ...globals.project,
            },
        }

        try {
            if (['destination', 'internal_destination'].includes(compoundConfiguration.type)) {
                const {
                    invocations,
                    logs: filterLogs,
                    metrics: filterMetrics,
                } = await this.hogExecutor.buildHogFunctionInvocations([compoundConfiguration], triggerGlobals)

                filterMetrics.forEach((metric) => {
                    if (metric.metric_name === 'filtered') {
                        logs.push({
                            level: 'info',
                            timestamp: DateTime.now(),
                            message: `Mapping trigger not matching filters was ignored.`,
                        })
                    }
                })

                filterLogs.forEach((log) => {
                    logs.push(log)
                })

                for (const invocation of invocations) {
                    invocation.id = invocationID

                    const options: HogExecutorExecuteAsyncOptions = buildHogExecutorAsyncOptions(
                        mock_async_functions,
                        logs
                    )

                    let response: any = null
                    if (isNativeHogFunction(compoundConfiguration)) {
                        response = await this.nativeDestinationExecutorService.execute(invocation)
                    } else if (isSegmentPluginHogFunction(compoundConfiguration)) {
                        response = await this.segmentDestinationExecutorService.execute(invocation)
                    } else {
                        response = await this.hogExecutor.executeWithAsyncFunctions(invocation, options)
                    }

                    logs = logs.concat(response.logs)
                    if (response.error) {
                        errors.push(response.error)
                    }
                }

                const wasSkipped = invocations.length === 0

                return {
                    result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs,
                }
            } else if (compoundConfiguration.type === 'transformation') {
                // NOTE: We override the ID so that the transformer doesn't cache the result
                compoundConfiguration.id = new UUIDT().toString()
                const pluginEvent: PluginEvent = {
                    ...triggerGlobals.event,
                    ip:
                        typeof triggerGlobals.event.properties.$ip === 'string'
                            ? triggerGlobals.event.properties.$ip
                            : null,
                    site_url: triggerGlobals.project.url,
                    team_id: triggerGlobals.project.id,
                    now: '',
                }
                const response = await this.hogTransformer.transformEvent(pluginEvent, [compoundConfiguration])

                result = response.event

                for (const invocationResult of response.invocationResults) {
                    logs = logs.concat(invocationResult.logs)
                    if (invocationResult.error) {
                        errors.push(invocationResult.error)
                    }
                }

                const wasSkipped = response.invocationResults.some((r) =>
                    r.metrics.some((m) => m.metric_name === 'filtered')
                )

                return {
                    result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs,
                }
            } else {
                throw new CdpInvocationError('Invalid function type', 400)
            }
        } finally {
            await this.hogFunctionMonitoringService.flush()
        }
    }

    async testHogFlowInvocation(req: ModifiedRequest): Promise<TestFlowResult> {
        const { id, team_id } = req.params
        const { clickhouse_event, configuration, invocation_id, current_action_id, mock_async_functions } = req.body

        logger.info('⚡️', 'Received hogflow invocation', { id, team_id, body: req.body })

        const invocationID = invocation_id ?? new UUIDT().toString()

        if (!UUID.validateString(invocationID)) {
            throw new CdpInvocationError('Invalid invocation ID', 400)
        }

        const isNewHogFlow = id === 'new'
        const hogFlow = isNewHogFlow ? null : await this.hogFlowManager.getHogFlow(id)

        const team = await this.hub.teamManager.getTeam(parseInt(team_id)).catch(() => null)

        if (!team) {
            throw new CdpInvocationError('Team not found', 404)
        }

        // The real security happens at the django layer so this is more of a sanity check
        if (!isNewHogFlow && (!hogFlow || hogFlow.team_id !== team.id)) {
            throw new CdpInvocationError('Hog flow not found', 404)
        }

        const globals: HogFunctionInvocationGlobals | null = clickhouse_event
            ? convertToHogFunctionInvocationGlobals(
                  clickhouse_event,
                  team,
                  this.hub.SITE_URL ?? 'http://localhost:8000'
              )
            : (req.body.globals ?? null)

        if (!globals || !globals.event) {
            throw new CdpInvocationError('Missing event', 400)
        }

        const compoundConfiguration = {
            ...hogFlow,
            ...configuration,
            team_id: team.id,
        }

        const triggerGlobals: HogFunctionInvocationGlobals = {
            ...globals,
            project: {
                id: team.id,
                name: team.name,
                url: `${this.hub.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
            },
        }

        const filterGlobals = convertToHogFunctionFilterGlobal({
            event: globals.event,
            person: globals.person,
            groups: globals.groups,
            variables: globals.variables || {},
        })

        const invocation = createHogFlowInvocation(triggerGlobals, compoundConfiguration, filterGlobals)

        invocation.state.currentAction = current_action_id
            ? {
                  id: current_action_id,
                  startedAtTimestamp: Date.now(),
              }
            : undefined

        const logs: MinimalLogEntry[] = []
        const options: HogExecutorExecuteAsyncOptions = buildHogExecutorAsyncOptions(mock_async_functions, logs)
        const result = await this.hogFlowExecutor.executeCurrentAction(invocation, { hogExecutorOptions: options })

        return {
            nextActionId: result.invocation.state.currentAction?.id,
            status: result.error ? 'error' : 'success',
            errors: result.error ? [result.error] : [],
            logs: [...result.logs, ...logs],
            variables: result.invocation.state.variables ?? {},
            execResult: result.execResult ?? null,
        }
    }

    async queueBatchInvocation(req: ModifiedRequest, kafkaProducer: KafkaProducerWrapper): Promise<void> {
        const { id, team_id, parent_run_id } = req.params

        logger.info('⚡️', 'Received hogflow batch invocation', { id, team_id, parent_run_id })

        const team = await this.hub.teamManager.getTeam(parseInt(team_id)).catch(() => null)

        if (!team) {
            throw new CdpInvocationError('Team not found', 404)
        }

        const hogFlow = await this.hogFlowManager.getHogFlow(id)

        if (!hogFlow || hogFlow.team_id !== team.id) {
            throw new CdpInvocationError('Workflow not found', 404)
        }

        if (hogFlow.trigger.type !== 'batch') {
            throw new CdpInvocationError('Only batch Workflows are supported for batch jobs', 400)
        }

        const batchHogFlowRequest = {
            teamId: team.id,
            hogFlowId: hogFlow.id,
            parentRunId: parent_run_id,
            filters: {
                properties: hogFlow.trigger.filters.properties || [],
                filter_test_accounts: req.body.filters?.filter_test_accounts || false,
            },
        }

        await kafkaProducer.produce({
            topic: KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
            value: Buffer.from(JSON.stringify(batchHogFlowRequest)),
            key: `${team.id}_${hogFlow.id}`,
        })
    }
}

const buildHogExecutorAsyncOptions = (
    mockAsyncFunctions: boolean,
    logs: MinimalLogEntry[]
): HogExecutorExecuteAsyncOptions => {
    let mockFunctions: Record<string, (...args: any[]) => any> | undefined

    if (mockAsyncFunctions) {
        mockFunctions = {}
        for (const name of getRegisteredAsyncFunctionNames()) {
            const handler = getAsyncFunctionHandler(name)!
            mockFunctions[name] = (...args: any[]) => handler.mock(args, logs)
        }
    }

    return {
        maxAsyncFunctions: MAX_ASYNC_STEPS,
        asyncFunctionsNames: mockAsyncFunctions ? [] : undefined,
        functions: mockFunctions,
    }
}
