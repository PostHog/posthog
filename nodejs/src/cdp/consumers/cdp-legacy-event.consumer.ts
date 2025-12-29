import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { LegacyPluginAppMetrics } from '~/cdp/legacy-plugins/app-metrics'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub, ISOTimestamp, PostIngestionEvent, ProjectId, RawClickHouseEvent } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { LazyLoader } from '../../utils/lazy-loader'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { LegacyWebhookService } from '../legacy-webhooks/legacy-webhook-service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { createInvocation } from '../utils/invocation-utils'
import { CdpConsumerBase } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export type LightweightPluginConfig = {
    id: number
    team_id: number
    plugin_id: number
    enabled: boolean
    config: Record<string, unknown>
    created_at: string
    updated_at?: string
    plugin?: {
        id: number
        url: string
    }
}

type PluginConfigHogFunction = {
    pluginConfigId: number
    hogFunction: HogFunctionType
}

const legacyPluginExecutionResultCounter = new Counter({
    name: 'cdp_legacy_event_consumer_execution_result_total',
    help: 'The number of times we have executed a legacy plugin',
    labelNames: ['result', 'template_id'],
})

/**
 * This is a temporary consumer that hooks into the existing onevent consumer group
 * It currently just runs the same logic as the old one but with noderdkafka as the consumer tech which should improve things
 * We can then use this to gradually move over to the new hog functions
 */
export class CdpLegacyEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpLegacyEventsConsumer'
    protected promiseScheduler = new PromiseScheduler()
    protected kafkaConsumer: KafkaConsumer

    private pluginConfigsLoader: LazyLoader<PluginConfigHogFunction[]>
    private legacyPluginExecutor: LegacyPluginExecutorService
    private legacyWebhookService: LegacyWebhookService

    private appMetrics: LegacyPluginAppMetrics

    constructor(hub: Hub) {
        super(hub)

        this.kafkaConsumer = new KafkaConsumer({
            groupId: hub.CDP_LEGACY_EVENT_CONSUMER_GROUP_ID,
            topic: hub.CDP_LEGACY_EVENT_CONSUMER_TOPIC,
        })

        this.legacyPluginExecutor = new LegacyPluginExecutorService(hub)
        this.legacyWebhookService = new LegacyWebhookService(hub)

        this.pluginConfigsLoader = new LazyLoader({
            name: 'plugin_config_hog_functions',
            loader: async (teamIds: string[]) => this.loadAndBuildHogFunctions(teamIds),
            refreshAgeMs: 600000, // 10 minutes
            refreshBackgroundAgeMs: 300000, // 5 minutes
            bufferMs: 10, // 10ms buffer for batching
        })

        this.appMetrics = new LegacyPluginAppMetrics(
            hub.kafkaProducer,
            hub.APP_METRICS_FLUSH_FREQUENCY_MS,
            hub.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
        )
    }

    private async loadAndBuildHogFunctions(teamIds: string[]): Promise<Record<string, PluginConfigHogFunction[]>> {
        const { rows } = await this.hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT
                posthog_pluginconfig.id,
                posthog_pluginconfig.team_id,
                posthog_pluginconfig.plugin_id,
                posthog_pluginconfig.enabled,
                posthog_pluginconfig.config,
                posthog_pluginconfig.created_at,
                posthog_pluginconfig.updated_at,
                posthog_plugin.id as plugin__id,
                posthog_plugin.url as plugin__url
            FROM posthog_pluginconfig
            LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
            WHERE posthog_pluginconfig.team_id = ANY($1)
                AND posthog_pluginconfig.enabled = 't'
                AND (posthog_pluginconfig.deleted IS NULL OR posthog_pluginconfig.deleted != 't')
                AND posthog_plugin.capabilities->'methods' @> '["onEvent"]'::jsonb`,
            [teamIds.map((id) => parseInt(id))],
            'loadPluginConfigHogFunctions'
        )

        // Group by team_id and build hog functions directly
        const results: Record<string, PluginConfigHogFunction[]> = {}

        for (const row of rows) {
            const teamId = row.team_id.toString()
            if (!results[teamId]) {
                results[teamId] = []
            }

            try {
                const hogFunction = this.convertPluginConfigToHogFunction({
                    id: row.id,
                    team_id: row.team_id,
                    plugin_id: row.plugin_id,
                    enabled: row.enabled === 't',
                    config: row.config,
                    created_at: row.created_at,
                    updated_at: row.updated_at,
                    plugin: row.plugin__url
                        ? {
                              id: row.plugin__id,
                              url: row.plugin__url,
                          }
                        : undefined,
                })

                if (hogFunction) {
                    results[teamId].push({
                        pluginConfigId: row.id,
                        hogFunction,
                    })
                }
            } catch (error: any) {
                logger.warn('Failed to convert plugin config to hog function', {
                    pluginConfigId: row.id,
                    error: error?.message,
                })
            }
        }

        // Ensure all requested team IDs are in the results
        for (const teamId of teamIds) {
            if (!results[teamId]) {
                results[teamId] = []
            }
        }

        return results
    }

    private convertPluginConfigToHogFunction(pluginConfig: LightweightPluginConfig): HogFunctionType | null {
        if (!pluginConfig.plugin?.url) {
            return null
        }

        // Extract plugin ID from URL (following the migration.py pattern)
        const pluginId = pluginConfig.plugin.url.replace('inline://', '').replace('https://github.com/PostHog/', '')

        const templateId = `plugin-${pluginId}`

        // Build inputs from plugin config
        const inputs: HogFunctionType['inputs'] = {}

        for (const [key, value] of Object.entries(pluginConfig.config)) {
            inputs[key] = { value: value?.toString() ?? '' }
        }

        // Add legacy_plugin_config_id for plugins that use legacy storage
        if (pluginId === 'customerio-plugin') {
            inputs.legacy_plugin_config_id = { value: pluginConfig.id }
        }

        // Create a HogFunctionType
        return {
            id: `legacy-${pluginConfig.id}`,
            type: 'destination' as const,
            team_id: pluginConfig.team_id,
            name: `Legacy Plugin ${pluginConfig.id}`,
            enabled: pluginConfig.enabled,
            deleted: false,
            hog: '',
            bytecode: [],
            template_id: templateId,
            inputs,
            filters: null,
            created_at: pluginConfig.created_at,
            updated_at: pluginConfig.updated_at ?? pluginConfig.created_at,
        }
    }

    @instrumented('cdpLegacyEventsConsumer.processEvent')
    public async processEvent(invocation: HogFunctionInvocationGlobals) {
        const event: PostIngestionEvent = {
            eventUuid: invocation.event.uuid,
            event: invocation.event.event,
            teamId: invocation.project.id,
            distinctId: invocation.event.distinct_id,
            properties: invocation.event.properties,
            timestamp: invocation.event.timestamp as ISOTimestamp,
            // None of these are actually used by the runOnEvent as it converts it to a PostIngestionEvent
            projectId: invocation.project.id as ProjectId,
            person_created_at: null,
            person_properties: {},
            person_id: undefined,
        }

        const invocations = await this.getLegacyPluginHogFunctionInvocations(invocation)

        const results = await Promise.all(
            invocations.map(async (invocation) => this.legacyPluginExecutor.execute(invocation))
        )

        for (const result of results) {
            const pluginConfigId = parseInt(result.invocation.hogFunction.id.replace('legacy-', ''))
            const error = result.error
            legacyPluginExecutionResultCounter
                .labels({
                    result: error ? 'error' : 'success',
                    template_id: result.invocation.hogFunction.template_id,
                })
                .inc()

            void this.promiseScheduler.schedule(
                this.appMetrics.queueMetric({
                    teamId: event.teamId,
                    pluginConfigId,
                    category: 'onEvent',
                    failures: error ? 1 : 0,
                    successes: error ? 0 : 1,
                })
            )
        }
    }

    @instrumented('cdpLegacyEventsConsumer.processBatch')
    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (invocationGlobals.length) {
            await Promise.all(invocationGlobals.map((x) => this.processEvent(x)))
        }

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: this.promiseScheduler.waitForAll(),
            invocations: [],
        }
    }

    // This consumer always parses from kafka
    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                    const team = await this.hub.teamManager.getTeam(clickHouseEvent.team_id)

                    if (!team) {
                        return
                    }

                    const pluginConfigHogFunctions = await this.pluginConfigsLoader.get(team.id.toString())

                    if (!pluginConfigHogFunctions?.length) {
                        return
                    }

                    events.push(convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.hub.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    private async getLegacyPluginHogFunctionInvocations(
        invocation: HogFunctionInvocationGlobals
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const pluginConfigHogFunctions = await this.pluginConfigsLoader.get(invocation.project.id.toString())

        if (!pluginConfigHogFunctions) {
            return []
        }

        return pluginConfigHogFunctions.map(({ hogFunction }) => {
            // Plugin configs are always static { value: any } so we can just convert to a record of strings
            const inputs = Object.entries(hogFunction.inputs || {}).reduce(
                (acc, [key, value]) => {
                    acc[key] = value?.value?.toString() ?? ''
                    return acc
                },
                {} as Record<string, string>
            )

            return createInvocation(
                {
                    ...invocation,
                    inputs,
                },
                hogFunction
            )
        })
    }

    public async start(): Promise<void> {
        await super.start()
        await this.legacyWebhookService.start()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpLegacyConsumer.handleEachBatch', async () => {
                const [webhookBatch, pluginBatch] = await Promise.all([
                    this.legacyWebhookService.processBatch(messages),
                    this._parseKafkaBatch(messages).then((invocations) => this.processBatch(invocations)),
                ])
                return { backgroundTask: Promise.all([webhookBatch.backgroundTask, pluginBatch.backgroundTask]) }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Stopping legacy webhook service...')
        await this.legacyWebhookService.stop()
        logger.info('💤', 'Flushing app metrics before stopping...')
        await this.appMetrics.flush()
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
