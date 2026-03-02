import { DateTime } from 'luxon'
import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS, KAFKA_WAREHOUSE_SOURCE_WEBHOOKS } from '~/config/kafka-topics'
import { KafkaProducerWrapper } from '~/kafka/producer'
import { PluginEvent } from '~/plugin-scaffold'

import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    PluginsServerConfig,
} from '../types'
import { logger } from '../utils/logger'
import { UUID, UUIDT, delay } from '../utils/utils'
import { getAsyncFunctionHandler, getRegisteredAsyncFunctionNames } from './async-function-registry'
import './async-functions'
import { createCdpCoreServices } from './cdp-services'
import { CdpConsumerBaseDeps } from './consumers/cdp-base.consumer'
import {
    CdpSourceWebhooksConsumer,
    HogFunctionWebhookResult,
    SourceWebhookError,
} from './consumers/cdp-source-webhooks.consumer'
import { HogTransformerService, createHogTransformerService } from './hog-transformations/hog-transformer.service'
import { BatchExportHogFunctionService, NotFoundError, ParseError } from './services/batch-export-hog-function.service'
import { HogExecutorExecuteAsyncOptions, HogExecutorService, MAX_ASYNC_STEPS } from './services/hog-executor.service'
import { HogFlowExecutorService, createHogFlowInvocation } from './services/hogflows/hogflow-executor.service'
import { HogFlowManagerService } from './services/hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from './services/managers/hog-function-manager.service'
import { EmailTrackingService } from './services/messaging/email-tracking.service'
import { RecipientTokensService } from './services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService } from './services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from './services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from './services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from './services/segment-destination-executor.service'
import { HOG_FUNCTION_TEMPLATES } from './templates'
import { HogFunctionInvocationGlobals, HogFunctionType, MinimalLogEntry } from './types'
import { convertToHogFunctionInvocationGlobals, isNativeHogFunction, isSegmentPluginHogFunction } from './utils'
import { convertToHogFunctionFilterGlobal } from './utils/hog-function-filtering'

export type CdpApiConfig = PluginsServerConfig
export type CdpApiDeps = CdpConsumerBaseDeps

export class CdpApi {
    private hogExecutor: HogExecutorService
    private nativeDestinationExecutorService: NativeDestinationExecutorService
    private segmentDestinationExecutorService: SegmentDestinationExecutorService

    private hogFunctionManager: HogFunctionManagerService
    private hogFlowManager: HogFlowManagerService

    private hogFlowExecutor: HogFlowExecutorService
    private hogWatcher: HogWatcherService
    private hogTransformer: HogTransformerService
    private hogFunctionMonitoringService: HogFunctionMonitoringService
    private cdpSourceWebhooksConsumer: CdpSourceWebhooksConsumer
    private emailTrackingService: EmailTrackingService
    private recipientTokensService: RecipientTokensService
    private cdpWarehouseKafkaProducer?: KafkaProducerWrapper
    private batchExportHogFunctionService: BatchExportHogFunctionService

    constructor(
        private config: PluginsServerConfig,
        private deps: CdpApiDeps
    ) {
        const services = createCdpCoreServices(config, deps, 'cdp-api-redis')

        this.hogFunctionManager = services.hogFunctionManager
        this.hogFlowManager = services.hogFlowManager
        this.recipientTokensService = services.recipientTokensService
        this.hogExecutor = services.hogExecutor
        this.hogFlowExecutor = services.hogFlowExecutor
        this.nativeDestinationExecutorService = services.nativeDestinationExecutorService
        this.segmentDestinationExecutorService = services.segmentDestinationExecutorService
        this.hogWatcher = services.hogWatcher
        this.hogFunctionMonitoringService = services.hogFunctionMonitoringService

        // API-only services
        this.hogTransformer = createHogTransformerService(config, deps)
        this.cdpSourceWebhooksConsumer = new CdpSourceWebhooksConsumer(config, deps)
        this.emailTrackingService = new EmailTrackingService(
            this.hogFunctionManager,
            this.hogFlowManager,
            this.hogFunctionMonitoringService
        )
        this.batchExportHogFunctionService = new BatchExportHogFunctionService(
            config.SITE_URL,
            deps.teamManager,
            this.hogFunctionManager,
            this.hogExecutor,
            this.hogWatcher,
            this.hogFunctionMonitoringService
        )
    }

    public get service(): PluginServerService {
        return {
            id: 'cdp-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? new HealthCheckResultError('CDP API is not healthy', {}),
        }
    }

    async start(): Promise<void> {
        this.cdpWarehouseKafkaProducer = await KafkaProducerWrapper.create(
            this.config.KAFKA_CLIENT_RACK,
            'WAREHOUSE_PRODUCER'
        )
        await this.cdpSourceWebhooksConsumer.start()
    }

    async stop(): Promise<void> {
        await Promise.all([
            this.cdpWarehouseKafkaProducer?.disconnect(),
            this.cdpSourceWebhooksConsumer.stop(),
            this.batchExportHogFunctionService.stop(),
        ])
    }

    isHealthy(): HealthCheckResult {
        // NOTE: There isn't really anything to check for here so we are just always healthy
        return new HealthCheckResultOk()
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: ModifiedRequest, res: express.Response) => Promise<void>) =>
            (req: ModifiedRequest, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        // API routes (authentication handled globally by middleware)
        router.post('/api/projects/:team_id/hog_functions/:id/invocations', asyncHandler(this.postFunctionInvocation))
        router.post('/api/projects/:team_id/hog_flows/:id/invocations', asyncHandler(this.postHogflowInvocation))
        router.post(
            '/api/projects/:team_id/hog_flows/:id/batch_invocations/:parent_run_id',
            asyncHandler(this.postHogFlowBatchInvocation)
        )
        router.get('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.getFunctionStatus()))
        router.patch('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.patchFunctionStatus()))
        router.get('/api/hog_functions/states', asyncHandler(this.getFunctionStates()))
        router.get('/api/hog_function_templates', this.getHogFunctionTemplates)
        router.post('/api/messaging/generate_preferences_token', asyncHandler(this.generatePreferencesToken()))
        router.get('/api/messaging/validate_preferences_token/:token', asyncHandler(this.validatePreferencesToken()))
        router.post(
            '/api/projects/:team_id/hog_functions/:hog_function_id/batch_export_invocations',
            asyncHandler(this.handleBatchExportHogFunction())
        )

        const publicBodySizeLimit = (req: ModifiedRequest, res: express.Response, next: express.NextFunction): void => {
            if (req.rawBody && req.rawBody.length > 512_000) {
                res.status(413).json({ error: 'Request entity too large' })
                return
            }
            next()
        }

        // Public routes (excluded from authentication by middleware)
        router.post(
            '/public/webhooks/dwh/:webhook_id',
            publicBodySizeLimit,
            asyncHandler(this.handleWarehouseSourceWebhook())
        )
        router.post('/public/webhooks/:webhook_id', publicBodySizeLimit, asyncHandler(this.handleWebhook()))
        router.get('/public/webhooks/:webhook_id', asyncHandler(this.handleWebhook()))
        router.get('/public/m/pixel', asyncHandler(this.getEmailTrackingPixel()))
        router.post('/public/m/ses_webhook', publicBodySizeLimit, express.text(), asyncHandler(this.postSesWebhook()))
        router.get('/public/m/redirect', asyncHandler(this.getEmailTrackingRedirect()))

        return router
    }

    private getHogFunctionTemplates = (req: ModifiedRequest, res: express.Response): void => {
        res.json(HOG_FUNCTION_TEMPLATES)
    }

    private getFunctionStatus =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<void> => {
            const { id } = req.params
            const summary = await this.hogWatcher.getPersistedState(id)

            res.json(summary)
        }

    private patchFunctionStatus =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<void> => {
            const { id } = req.params
            const { state } = req.body

            // Check that state is valid
            if (!Object.values(HogWatcherState).includes(state)) {
                res.status(400).json({ error: 'Invalid state' })
                return
            }

            const summary = await this.hogWatcher.getPersistedState(id)
            const hogFunction = await this.hogFunctionManager.fetchHogFunction(id)

            if (!hogFunction) {
                res.status(404).json({ error: 'Hog function not found' })
                return
            }

            // Only allow patching the status if it is different from the current status

            if (summary.state !== state) {
                await this.hogWatcher.forceStateChange(hogFunction, state)
            }

            // Hacky - wait for a little to give a chance for the state to change
            await delay(100)

            res.json(await this.hogWatcher.getPersistedState(id))
        }

    private getFunctionStates =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<void> => {
            try {
                const allStates = await this.hogWatcher.getAllFunctionStates()

                // Transform the data for better consumption by Grafana and sort by tokens ascending
                const statesArray = Object.entries(allStates)
                    .map(([functionId, state]) => ({
                        function_id: functionId,
                        state: HogWatcherState[state.state], // Convert numeric state to readable string
                        tokens: state.tokens,
                        state_numeric: state.state,
                    }))
                    .sort((a, b) => b.state_numeric - a.state_numeric)

                const hogFunctions = await this.hogFunctionManager.getHogFunctions(
                    statesArray.map((x) => x.function_id)
                )

                const results = statesArray.map((x) => ({
                    ...x,
                    function_name: hogFunctions[x.function_id]?.name,
                    function_team_id: hogFunctions[x.function_id]?.team_id,
                    function_type: hogFunctions[x.function_id]?.type,
                    function_enabled: hogFunctions[x.function_id]?.enabled && !hogFunctions[x.function_id]?.deleted,
                }))

                res.json({
                    results,
                    total: results.length,
                })
            } catch (error) {
                logger.error('[CdpApi] Error getting all function states', error)
                res.status(500).json({ error: 'Failed to get function states' })
            }
        }

    private postFunctionInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            const { id, team_id } = req.params
            const { clickhouse_event, mock_async_functions, configuration, invocation_id } = req.body
            let { globals } = req.body

            logger.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

            const invocationID = invocation_id ?? new UUIDT().toString()

            // Check the invocationId is a valid UUID
            if (!UUID.validateString(invocationID)) {
                res.status(400).json({ error: 'Invalid invocation ID' })
                return
            }

            const isNewFunction = req.params.id === 'new'

            const hogFunction = isNewFunction
                ? null
                : await this.hogFunctionManager.fetchHogFunction(req.params.id).catch(() => null)
            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            globals = clickhouse_event
                ? convertToHogFunctionInvocationGlobals(clickhouse_event, team, this.config.SITE_URL)
                : globals

            if (!globals || !globals.event) {
                res.status(400).json({ error: 'Missing event' })
                return
            }

            // NOTE: We allow the hog function to be null if it is a "new" hog function
            // The real security happens at the django layer so this is more of a sanity check
            if (!isNewFunction && (!hogFunction || hogFunction.team_id !== team.id)) {
                return res.status(404).json({ error: 'Hog function not found' })
            }

            // We use the provided config if given, otherwise the function's config
            const compoundConfiguration: HogFunctionType = {
                ...hogFunction,
                ...configuration,
                team_id: team.id,
            }

            let logs: MinimalLogEntry[] = []
            let result: any = null
            const errors: any[] = []

            const triggerGlobals: HogFunctionInvocationGlobals = {
                ...globals,
                project: {
                    id: team.id,
                    name: team.name,
                    url: `${this.config.SITE_URL}/project/${team.id}`,
                    ...globals.project,
                },
            }

            if (['destination', 'internal_destination'].includes(compoundConfiguration.type)) {
                const {
                    invocations,
                    logs: filterLogs,
                    metrics: filterMetrics,
                } = await this.hogExecutor.buildHogFunctionInvocations([compoundConfiguration], triggerGlobals)

                // Add metrics to the logs
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

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                })
            } else if (compoundConfiguration.type === 'transformation') {
                // NOTE: We override the ID so that the transformer doesn't cache the result
                // TODO: We could do this with a "special" ID to indicate no caching...
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

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                })
            } else {
                return res.status(400).json({ error: 'Invalid function type' })
            }
        } catch (e) {
            console.error(e)
            res.status(500).json({ errors: [e.message] })
        } finally {
            await this.hogFunctionMonitoringService.flush()
        }
    }

    private postHogflowInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            const { id, team_id } = req.params
            const { clickhouse_event, configuration, invocation_id, current_action_id, mock_async_functions } = req.body

            logger.info('⚡️', 'Received hogflow invocation', { id, team_id, body: req.body })

            const invocationID = invocation_id ?? new UUIDT().toString()

            // Check the invocationId is a valid UUID
            if (!UUID.validateString(invocationID)) {
                res.status(400).json({ error: 'Invalid invocation ID' })
                return
            }

            const isNewHogFlow = req.params.id === 'new'
            const hogFlow = isNewHogFlow ? null : await this.hogFlowManager.getHogFlow(req.params.id)

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            // NOTE: We allow the hog flow to be null if it is a "new" hog flow
            // The real security happens at the django layer so this is more of a sanity check
            if (!isNewHogFlow && (!hogFlow || hogFlow.team_id !== team.id)) {
                return res.status(404).json({ error: 'Hog flow not found' })
            }

            const globals: HogFunctionInvocationGlobals | null = clickhouse_event
                ? convertToHogFunctionInvocationGlobals(
                      clickhouse_event,
                      team,
                      this.config.SITE_URL ?? 'http://localhost:8000'
                  )
                : req.body.globals

            if (!globals || !globals.event) {
                return res.status(400).json({ error: 'Missing event' })
            }

            // We use the provided config if given, otherwise the flow's config
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
                    url: `${this.config.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
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

            res.json({
                nextActionId: result.invocation.state.currentAction?.id,
                status: result.error ? 'error' : 'success',
                errors: result.error ? [result.error] : [],
                logs: [...result.logs, ...logs],
                variables: result.invocation.state.variables ?? {},
                execResult: result.execResult ?? null,
            })
        } catch (e) {
            console.error(e)
            res.status(500).json({ error: [e.message] })
        }
    }

    private postHogFlowBatchInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            const { id, team_id, parent_run_id } = req.params

            logger.info('⚡️', 'Received hogflow batch invocation', { id, team_id, parent_run_id })

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            const hogFlow = await this.hogFlowManager.getHogFlow(id)

            if (!hogFlow || hogFlow.team_id !== team.id) {
                return res.status(404).json({ error: 'Workflow not found' })
            }

            // Queue a message for the CDP batch producer to consume
            const kafkaProducer = this.deps.kafkaProducer
            if (!kafkaProducer) {
                return res.status(500).json({ error: 'Kafka producer not available' })
            }

            if (hogFlow.trigger.type !== 'batch') {
                return res.status(400).json({ error: 'Only batch Workflows are supported for batch jobs' })
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

            res.json({ status: 'queued' })
        } catch (e) {
            logger.error('Error handling hogflow batch invocation', { error: e })
            res.status(500).json({ error: [e.message] })
        }
    }

    private async processAndRespondToWebhook(
        webhookId: string,
        req: ModifiedRequest,
        res: express.Response,
        onSuccess: (
            result: Awaited<ReturnType<typeof this.cdpSourceWebhooksConsumer.processWebhook>>
        ) => Promise<any> | any
    ): Promise<any> {
        try {
            const result = await this.cdpSourceWebhooksConsumer.processWebhook(webhookId, req)

            if (typeof result.execResult === 'object' && result.execResult && 'httpResponse' in result.execResult) {
                const httpResponse = result.execResult.httpResponse as HogFunctionWebhookResult
                if (typeof httpResponse.body === 'string') {
                    return res
                        .status(httpResponse.status)
                        .set('Content-Type', httpResponse.contentType ?? 'text/plain')
                        .send(httpResponse.body)
                } else if (typeof httpResponse.body === 'object') {
                    return res.status(httpResponse.status).json(httpResponse.body)
                }
                return res.status(httpResponse.status).send('')
            }

            return await onSuccess(result)
        } catch (error) {
            if (error instanceof SourceWebhookError) {
                return res.status(error.status).json({ error: error.message })
            }
            logger.error('[CdpApi] Error handling webhook', { error })
            return res.status(500).json({ error: 'Internal error' })
        }
    }

    private handleWebhook =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            const { webhook_id } = req.params
            return this.processAndRespondToWebhook(webhook_id, req, res, (result) => {
                if (result.error) {
                    return res.status(500).json({ status: 'Unhandled error' })
                }
                if (!result.finished) {
                    return res.status(201).json({ status: 'queued' })
                }
                return res.status(200).json({ status: 'ok' })
            })
        }

    private handleWarehouseSourceWebhook =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            const { webhook_id } = req.params
            return this.processAndRespondToWebhook(webhook_id, req, res, async (result) => {
                if (result.error) {
                    return res.status(500).json({ error: 'Internal error' })
                }
                if (!result.execResult || typeof result.execResult !== 'object') {
                    return res.status(500).json({ error: 'Template did not return a payload' })
                }

                const hogFunction = result.invocation.hogFunction
                const schemaId = hogFunction.inputs?.schema_id?.value
                if (!schemaId) {
                    return res.status(500).json({ error: 'Missing schema_id on hog function' })
                }

                const kafkaProducer = this.cdpWarehouseKafkaProducer
                if (!kafkaProducer) {
                    return res.status(500).json({ error: 'Kafka producer not available' })
                }

                await kafkaProducer.produce({
                    topic: KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
                    key: `${hogFunction.team_id}:${schemaId}`,
                    value: Buffer.from(JSON.stringify(result.execResult)),
                })

                return res.status(200).json({ status: 'ok' })
            })
        }

    private postSesWebhook =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            try {
                const { status, message } = await this.emailTrackingService.handleSesWebhook(req)
                return res.status(status).json({ message })
            } catch (error) {
                return res.status(500).json({ error: 'Internal error' })
            }
        }

    private getEmailTrackingPixel =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            await this.emailTrackingService.handleEmailTrackingPixel(req, res)
        }

    private getEmailTrackingRedirect =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            await this.emailTrackingService.handleEmailTrackingRedirect(req, res)
        }

    private generatePreferencesToken =
        () =>
        (req: ModifiedRequest, res: express.Response): any => {
            const { team_id, identifier } = req.body

            if (!team_id || !identifier) {
                return res.status(400).json({ error: 'Team ID and identifier are required' })
            }

            const token = this.recipientTokensService.generatePreferencesToken({
                team_id,
                identifier,
            })
            return res.status(200).json({ token })
        }

    private validatePreferencesToken =
        () =>
        (req: ModifiedRequest, res: express.Response): any => {
            try {
                const { token } = req.params

                if (!token) {
                    return res.status(400).json({ error: 'Token is required' })
                }

                const result = this.recipientTokensService.validatePreferencesToken(token)

                if (!result.valid) {
                    return res.status(400).json({ error: 'Invalid or expired token' })
                }

                return res.status(200).json({
                    valid: result.valid,
                    team_id: result.team_id,
                    identifier: result.identifier,
                })
            } catch (error) {
                logger.error('[CdpApi] Error validating preferences token', error)
                return res.status(500).json({ error: 'Failed to validate token' })
            }
        }

    private handleBatchExportHogFunction =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            try {
                const result = await this.batchExportHogFunctionService.execute(
                    {
                        team_id: req.params.team_id,
                        hog_function_id: req.params.hog_function_id,
                    },
                    req.body
                )

                return res.json({
                    status: result.error ? 'error' : 'success',
                    errors: result.error ? [String(result.error)] : [],
                    logs: result.logs,
                })
            } catch (e) {
                if (e instanceof NotFoundError) {
                    return res.status(404).json({ errors: [e.message] })
                } else if (e instanceof ParseError) {
                    return res.status(400).json({ errors: [e.message] })
                } else {
                    console.error(e)
                    return res.status(500).json({ errors: [e.message] })
                }
            }
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
