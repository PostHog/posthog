import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { KAFKA_WAREHOUSE_SOURCE_WEBHOOKS } from '~/config/kafka-topics'
import { KafkaProducerWrapper } from '~/kafka/producer'
import { PluginEvent } from '~/plugin-scaffold'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, Hub, PluginServerService } from '../types'
import { logger } from '../utils/logger'
import { delay } from '../utils/utils'
import './async-functions'
import {
    CdpSourceWebhooksConsumer,
    CdpSourceWebhooksConsumerHub,
    HogFunctionWebhookResult,
    SourceWebhookError,
} from './consumers/cdp-source-webhooks.consumer'
import { HogTransformerHub, HogTransformerService } from './hog-transformations/hog-transformer.service'
import { CdpInvocationAPIService, CdpInvocationError } from './services/cdp-invocation-api.service'
import { HogExecutorService } from './services/hog-executor.service'
import { HogFlowExecutorService } from './services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from './services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from './services/hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from './services/managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from './services/managers/hog-function-template-manager.service'
import { RecipientsManagerService } from './services/managers/recipients-manager.service'
import { EmailTrackingService } from './services/messaging/email-tracking.service'
import { RecipientPreferencesService } from './services/messaging/recipient-preferences.service'
import { RecipientTokensService } from './services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService } from './services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from './services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from './services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from './services/segment-destination-executor.service'
import { HOG_FUNCTION_TEMPLATES } from './templates'
import { HogFunctionType } from './types'

/**
 * Hub type for CdpApi.
 * Combines all hub types needed by CdpApi and its dependencies.
 */
export type CdpApiHub = CdpSourceWebhooksConsumerHub &
    HogTransformerHub &
    Pick<
        Hub,
        | 'teamManager'
        | 'SITE_URL'
        | 'REDIS_URL'
        | 'REDIS_POOL_MIN_SIZE'
        | 'REDIS_POOL_MAX_SIZE'
        | 'CDP_REDIS_HOST'
        | 'CDP_REDIS_PORT'
        | 'CDP_REDIS_PASSWORD'
    >

export class CdpApi {
    private hogExecutor: HogExecutorService
    private nativeDestinationExecutorService: NativeDestinationExecutorService
    private segmentDestinationExecutorService: SegmentDestinationExecutorService

    private hogFunctionManager: HogFunctionManagerService
    private hogFunctionTemplateManager: HogFunctionTemplateManagerService
    private hogFlowManager: HogFlowManagerService
    private recipientsManager: RecipientsManagerService

    private hogFlowExecutor: HogFlowExecutorService
    private hogFlowFunctionsService: HogFlowFunctionsService
    private hogWatcher: HogWatcherService
    private hogTransformer: HogTransformerService
    private hogFunctionMonitoringService: HogFunctionMonitoringService
    private cdpSourceWebhooksConsumer: CdpSourceWebhooksConsumer
    private emailTrackingService: EmailTrackingService
    private recipientPreferencesService: RecipientPreferencesService
    private recipientTokensService: RecipientTokensService
    private cdpWarehouseKafkaProducer?: KafkaProducerWrapper
    private invocationTestingService: CdpInvocationAPIService

    constructor(private hub: CdpApiHub) {
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub.postgres)
        this.hogFlowManager = new HogFlowManagerService(hub.postgres, hub.pubSub)
        this.recipientsManager = new RecipientsManagerService(hub.postgres)
        this.hogExecutor = new HogExecutorService(hub)
        this.hogFlowFunctionsService = new HogFlowFunctionsService(
            hub.SITE_URL,
            this.hogFunctionTemplateManager,
            this.hogExecutor
        )
        this.recipientPreferencesService = new RecipientPreferencesService(this.recipientsManager)
        this.recipientTokensService = new RecipientTokensService(hub)
        this.hogFlowExecutor = new HogFlowExecutorService(
            this.hogFlowFunctionsService,
            this.recipientPreferencesService
        )
        this.nativeDestinationExecutorService = new NativeDestinationExecutorService(hub)
        this.segmentDestinationExecutorService = new SegmentDestinationExecutorService(hub)
        // CDP uses its own Redis instance with fallback to default
        this.hogWatcher = new HogWatcherService(
            hub,
            createRedisV2PoolFromConfig({
                connection: hub.CDP_REDIS_HOST
                    ? {
                          url: hub.CDP_REDIS_HOST,
                          options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                          name: 'cdp-api-redis',
                      }
                    : { url: hub.REDIS_URL, name: 'cdp-api-redis-fallback' },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
        )
        this.hogTransformer = new HogTransformerService(hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
        this.cdpSourceWebhooksConsumer = new CdpSourceWebhooksConsumer(hub)
        this.emailTrackingService = new EmailTrackingService(
            this.hogFunctionManager,
            this.hogFlowManager,
            this.hogFunctionMonitoringService
        )
        this.invocationTestingService = new CdpInvocationAPIService(
            hub,
            this.hogFunctionManager,
            this.hogFlowManager,
            this.hogExecutor,
            this.hogFlowExecutor,
            this.nativeDestinationExecutorService,
            this.segmentDestinationExecutorService,
            this.hogTransformer,
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
            this.hub.KAFKA_CLIENT_RACK,
            'WAREHOUSE_PRODUCER'
        )
        await this.cdpSourceWebhooksConsumer.start()
    }

    async stop(): Promise<void> {
        await Promise.all([this.cdpWarehouseKafkaProducer?.disconnect(), this.cdpSourceWebhooksConsumer.stop()])
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

    // -- Invocation handlers (delegate to CdpInvocationAPIService) --

    private postFunctionInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            res.json(await this.invocationTestingService.testHogFunctionInvocation(req))
        } catch (e) {
            if (e instanceof CdpInvocationError) {
                return res.status(e.statusCode).json({ error: e.message })
            }
            console.error(e)
            res.status(500).json({ errors: [e.message] })
        }
    }

    private postHogflowInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            res.json(await this.invocationTestingService.testHogFlowInvocation(req))
        } catch (e) {
            if (e instanceof CdpInvocationError) {
                return res.status(e.statusCode).json({ error: e.message })
            }
            console.error(e)
            res.status(500).json({ error: [e.message] })
        }
    }

    private postHogFlowBatchInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            const kafkaProducer = this.hub.kafkaProducer
            if (!kafkaProducer) {
                return res.status(500).json({ error: 'Kafka producer not available' })
            }

            await this.invocationTestingService.queueBatchInvocation(req, kafkaProducer)
            res.json({ status: 'queued' })
        } catch (e) {
            if (e instanceof CdpInvocationError) {
                return res.status(e.statusCode).json({ error: e.message })
            }
            logger.error('Error handling hogflow batch invocation', { error: e })
            res.status(500).json({ error: [e.message] })
        }
    }

    // -- Monitoring handlers --

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
                    function_type: (hogFunctions[x.function_id] as HogFunctionType | undefined)?.type,
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

    // -- Webhook handlers (delegate to CdpSourceWebhooksConsumer) --

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

    // -- Messaging handlers (delegate to EmailTrackingService / RecipientTokensService) --

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
}
