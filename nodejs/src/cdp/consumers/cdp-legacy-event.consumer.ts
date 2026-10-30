import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { validTeamIds } from '~/common/utils/team-manager'

import {
    HealthCheckResult,
    ISOTimestamp,
    PluginsServerConfig,
    PostIngestionEvent,
    ProjectId,
    RawClickHouseEvent,
    Team,
} from '../../types'
import { LegacyWebhookService } from '../legacy-webhooks/legacy-webhook-service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import type {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { createInvocation } from '../utils/invocation-utils'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { parseBatch } from './message-parsing'

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
    /** Null once the plugin config has been migrated and the hog function row is the source of truth */
    pluginConfigId: number | null
    hogFunction: HogFunctionType
}

type TeamWithPluginConfigs = { team: Team; pluginConfigs: PluginConfigHogFunction[] }

const legacyPluginExecutionResultCounter = new Counter({
    name: 'cdp_legacy_event_consumer_execution_result_total',
    help: 'The number of times we have executed a legacy plugin',
    // `source` says which representation the consumer picked, so a migration can be watched as the
    // share moving from plugin_config to hog_function while result stays where it was
    labelNames: ['result', 'template_id', 'source'],
})

export type CdpLegacyEventsConsumerConfig = CdpConsumerBaseConfig &
    Pick<PluginsServerConfig, 'CDP_LEGACY_EVENT_CONSUMER_TOPIC' | 'CDP_LEGACY_EVENT_CONSUMER_GROUP_ID' | 'SITE_URL'>

/**
 * This is a temporary consumer that hooks into the existing onevent consumer group
 * It currently just runs the same logic as the old one but with noderdkafka as the consumer tech which should improve things
 * We can then use this to gradually move over to the new hog functions
 */
export class CdpLegacyEventsConsumer extends CdpConsumerBase<CdpLegacyEventsConsumerConfig> {
    protected name = 'CdpLegacyEventsConsumer'
    protected promiseScheduler = new PromiseScheduler()
    protected kafkaConsumer: KafkaConsumerInterface

    private pluginConfigsLoader: LazyLoader<PluginConfigHogFunction[]>
    // Execution reads the plugin configs that _parseKafkaBatch loaded. A second lookup could fail after this
    // batch's webhooks start, and reading the batch again would then send those webhooks twice.
    private pluginConfigsByGlobals = new WeakMap<HogFunctionInvocationGlobals, PluginConfigHogFunction[]>()
    private legacyPluginExecutor: LegacyPluginExecutorService
    private legacyWebhookService: LegacyWebhookService

    constructor(
        config: CdpLegacyEventsConsumerConfig,
        protected override deps: CdpConsumerBaseDeps
    ) {
        super(config, deps)

        this.kafkaConsumer = createKafkaConsumer({
            groupId: config.CDP_LEGACY_EVENT_CONSUMER_GROUP_ID,
            topic: config.CDP_LEGACY_EVENT_CONSUMER_TOPIC,
        })

        this.legacyPluginExecutor = new LegacyPluginExecutorService(deps.postgres, deps.geoipService)
        this.legacyWebhookService = new LegacyWebhookService(deps.postgres, deps.teamManager, deps.pubSub)

        this.pluginConfigsLoader = new LazyLoader({
            name: 'plugin_config_hog_functions',
            loader: async (teamIds: string[]) => this.loadAndBuildHogFunctions(teamIds),
            refreshAgeMs: 600000, // 10 minutes
            refreshBackgroundAgeMs: 300000, // 5 minutes
            bufferMs: 10, // 10ms buffer for batching
            loaderRetry: DEFAULT_LOADER_RETRY,
        })

        // This loader caches the combined plugin-config and migrated-function view, so the manager
        // invalidating its own copy is not enough: enabling or deleting a migrated row has to change
        // which of the two runs straight away, not at the next refresh.
        deps.pubSub.on<{ teamId: number }>('reload-hog-functions', ({ teamId }) => {
            this.pluginConfigsLoader.markForRefresh(teamId.toString())
        })
    }

    private async loadAndBuildHogFunctions(teamIds: string[]): Promise<Record<string, PluginConfigHogFunction[]>> {
        const numericTeamIds = validTeamIds(teamIds)
        const { rows } = await this.deps.postgres.query(
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
            [numericTeamIds],
            'loadPluginConfigHogFunctions'
        )

        // Load attachments for all plugin configs with non-empty config
        const pluginConfigIds = rows.filter((row) => Object.keys(row.config || {}).length > 0).map((row) => row.id)
        const attachmentsMap: Record<number, Record<string, any>> = {}

        if (pluginConfigIds.length > 0) {
            const { rows: attachmentRows } = await this.deps.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT plugin_config_id, key, contents
                FROM posthog_pluginattachment
                WHERE plugin_config_id = ANY($1)`,
                [pluginConfigIds],
                'loadPluginConfigAttachments'
            )

            for (const attachmentRow of attachmentRows) {
                if (!attachmentsMap[attachmentRow.plugin_config_id]) {
                    attachmentsMap[attachmentRow.plugin_config_id] = {}
                }

                try {
                    // Convert Buffer to string if needed, then parse as JSON
                    let contentsString: string
                    if (Buffer.isBuffer(attachmentRow.contents)) {
                        contentsString = attachmentRow.contents.toString('utf-8')
                    } else if (typeof attachmentRow.contents === 'string') {
                        contentsString = attachmentRow.contents
                    } else {
                        // If it's already an object, use it directly
                        attachmentsMap[attachmentRow.plugin_config_id][attachmentRow.key] = attachmentRow.contents
                        continue
                    }

                    const contents = parseJSON(contentsString)
                    attachmentsMap[attachmentRow.plugin_config_id][attachmentRow.key] = contents
                } catch (error: any) {
                    logger.warn('Failed to parse attachment contents', {
                        pluginConfigId: attachmentRow.plugin_config_id,
                        key: attachmentRow.key,
                        error: error?.message,
                    })
                }
            }
        }

        // Group by team_id and build hog functions directly
        const results: Record<string, PluginConfigHogFunction[]> = {}

        for (const row of rows) {
            const teamId = row.team_id.toString()
            if (!results[teamId]) {
                results[teamId] = []
            }

            try {
                const hogFunction = this.convertPluginConfigToHogFunction(
                    {
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
                    },
                    attachmentsMap[row.id]
                )

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

        return this.preferMigratedHogFunctions(results, await this.loadMigratedHogFunctions(numericTeamIds))
    }

    private async loadMigratedHogFunctions(teamIds: number[]): Promise<Record<string, HogFunctionType[]>> {
        const byTeam = await this.hogFunctionManager.getHogFunctionsForTeams(teamIds, ['legacy_destination'])

        return Object.fromEntries(Object.entries(byTeam).map(([teamId, fns]) => [teamId, fns]))
    }

    // Both representations would run the same processor. Production has at most one enabled onEvent
    // plugin config per team and plugin, so the template id identifies the pair and the migrated row wins.
    private preferMigratedHogFunctions(
        fromPluginConfigs: Record<string, PluginConfigHogFunction[]>,
        fromHogFunctions: Record<string, HogFunctionType[]>
    ): Record<string, PluginConfigHogFunction[]> {
        const results: Record<string, PluginConfigHogFunction[]> = {}

        for (const [teamId, pluginConfigFns] of Object.entries(fromPluginConfigs)) {
            // Nothing in the database stops two migrated rows sharing a template, and running both
            // would send every event twice. Keep the oldest and ignore the rest.
            const byTemplate = new Map<string, HogFunctionType>()
            for (const fn of [...(fromHogFunctions[teamId] ?? [])].sort((a, b) => a.id.localeCompare(b.id))) {
                const templateId = fn.template_id ?? ''
                if (!byTemplate.has(templateId)) {
                    byTemplate.set(templateId, fn)
                }
            }

            const migrated = [...byTemplate.values()]
            const migratedTemplateIds = new Set(migrated.map((fn) => fn.template_id))

            results[teamId] = [
                ...pluginConfigFns.filter((x) => !migratedTemplateIds.has(x.hogFunction.template_id)),
                ...migrated.map((hogFunction) => ({ pluginConfigId: null, hogFunction })),
            ]
        }

        return results
    }

    private convertPluginConfigToHogFunction(
        pluginConfig: LightweightPluginConfig,
        attachments?: Record<string, any>
    ): HogFunctionType | null {
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

        // Add attachments to inputs (matching migration.py logic)
        if (attachments && Object.keys(pluginConfig.config).length > 0) {
            for (const [key, value] of Object.entries(attachments)) {
                if (value) {
                    inputs[key] = { value }
                }
            }
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
            invocations.map(async ({ invocation, pluginConfigId }) =>
                this.legacyPluginExecutor.execute(invocation).then((result) => ({ result, pluginConfigId }))
            )
        )

        for (const { result, pluginConfigId } of results) {
            const error = result.error

            legacyPluginExecutionResultCounter
                .labels({
                    result: error ? 'error' : 'success',
                    template_id: result.invocation.hogFunction.template_id,
                    source: pluginConfigId !== null ? 'plugin_config' : 'hog_function',
                })
                .inc()

            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    team_id: event.teamId,
                    app_source_id: pluginConfigId !== null ? String(pluginConfigId) : result.invocation.hogFunction.id,
                    metric_kind: error ? 'failure' : 'success',
                    metric_name: error ? 'failed' : 'succeeded',
                    count: 1,
                },
                pluginConfigId !== null ? 'legacy_plugin' : 'hog_function'
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
        return await parseBatch<TeamWithPluginConfigs>(messages, {
            errorLog: 'Error parsing message',
            parse: (message) => {
                const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent
                return {
                    teamId: clickHouseEvent.team_id,
                    toGlobals: ({ team, pluginConfigs }) => {
                        const globals = convertToHogFunctionInvocationGlobals(
                            clickHouseEvent,
                            team,
                            this.config.SITE_URL
                        )
                        this.pluginConfigsByGlobals.set(globals, pluginConfigs)
                        return globals
                    },
                }
            },
            loadTeam: async (teamId) => {
                const team = await this.deps.teamManager.getTeam(teamId)
                if (!team) {
                    return null
                }
                const pluginConfigs = await this.pluginConfigsLoader.get(team.id.toString())
                return pluginConfigs?.length ? { team, pluginConfigs } : null
            },
        })
    }

    private async getLegacyPluginHogFunctionInvocations(
        invocation: HogFunctionInvocationGlobals
    ): Promise<{ invocation: CyclotronJobInvocationHogFunction; pluginConfigId: number | null }[]> {
        // The batch handler always finds the configs that _parseKafkaBatch stored, so it never makes a second lookup.
        // Only callers that build their own globals reach the loader call.
        const pluginConfigHogFunctions =
            this.pluginConfigsByGlobals.get(invocation) ??
            (await this.pluginConfigsLoader.get(invocation.project.id.toString()))

        if (!pluginConfigHogFunctions) {
            return []
        }

        return pluginConfigHogFunctions.map(({ hogFunction, pluginConfigId }) => {
            // Plugin configs are always static { value: any } so we can just convert to a record of strings.
            // A migrated row keeps its secrets in encrypted_inputs, which the manager decrypts separately.
            const inputs = Object.entries({ ...hogFunction.inputs, ...hogFunction.encrypted_inputs }).reduce(
                (acc, [key, value]) => {
                    acc[key] = value?.value
                    return acc
                },
                {} as Record<string, string>
            )

            return {
                pluginConfigId,
                invocation: createInvocation(
                    {
                        ...invocation,
                        inputs,
                    },
                    hogFunction
                ),
            }
        })
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.legacyWebhookService.start()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpLegacyConsumer.handleEachBatch', async () => {
                // Both parses finish before either side sends. A parse lookup error then fails the batch
                // before it sends a webhook or a plugin call, so reading the batch again does not repeat one.
                const [webhookEvents, invocations] = await Promise.all([
                    this.legacyWebhookService.parseBatch(messages),
                    this._parseKafkaBatch(messages),
                ])
                const webhookBatch = this.legacyWebhookService.processEvents(webhookEvents)
                const pluginBatch = await this.processBatch(invocations)
                return {
                    backgroundTask: Promise.all([webhookBatch.backgroundTask, pluginBatch.backgroundTask]).then(() =>
                        this.invocationResultsService.flush()
                    ),
                }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Stopping legacy webhook service...')
        await this.legacyWebhookService.stop()
        logger.info('💤', 'Flushing invocation results before stopping...')
        await this.invocationResultsService.flush()
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
