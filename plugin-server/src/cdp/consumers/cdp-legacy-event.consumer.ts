import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { instrumented } from '~/common/tracing/tracing-utils'
import { buildIntegerMatcher } from '~/config/config'
import { chainToElements } from '~/utils/db/elements-chain'
import { pluginActionMsSummary } from '~/worker/metrics'
import { vmFetchTracker } from '~/worker/vm/tracked-fetch'

import { parseKafkaHeaders } from '../../kafka/consumer'
import {
    Hub,
    ISOTimestamp,
    PluginConfig,
    PluginMethodsConcrete,
    PostIngestionEvent,
    ProjectId,
    RawClickHouseEvent,
    ValueMatcher,
} from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { LazyLoader } from '../../utils/lazy-loader'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { LegacyPluginExecutorService, legacyFetchTracker } from '../services/legacy-plugin-executor.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { createInvocation } from '../utils/invocation-utils'
import { CdpEventsConsumer } from './cdp-events.consumer'
import { counterParseError } from './metrics'

type LightweightPluginConfig = {
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

const legacyPluginConfigComparisonCounter = new Counter({
    name: 'cdp_legacy_event_consumer_plugin_config_comparison_total',
    help: 'The number of times we have compared plugin configs to hog functions',
    labelNames: ['result'],
})

/**
 * This is a temporary consumer that hooks into the existing onevent consumer group
 * It currently just runs the same logic as the old one but with noderdkafka as the consumer tech which should improve things
 * We can then use this to gradually move over to the new hog functions
 */
export class CdpLegacyEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpLegacyEventsConsumer'
    protected promiseScheduler = new PromiseScheduler()

    private pluginConfigsToSkipElementsParsing: ValueMatcher<number>
    private pluginConfigsLoader: LazyLoader<PluginConfigHogFunction[]>
    private legacyPluginExecutor: LegacyPluginExecutorService

    constructor(hub: Hub) {
        super(hub, hub.CDP_LEGACY_EVENT_CONSUMER_TOPIC, hub.CDP_LEGACY_EVENT_CONSUMER_GROUP_ID)

        this.legacyPluginExecutor = new LegacyPluginExecutorService(hub)

        logger.info('🔁', `CdpLegacyEventsConsumer setup`, {
            pluginConfigs: Array.from(this.hub.pluginConfigsPerTeam.keys()),
        })

        this.pluginConfigsToSkipElementsParsing = buildIntegerMatcher(process.env.SKIP_ELEMENTS_PARSING_PLUGINS, true)

        this.pluginConfigsLoader = new LazyLoader({
            name: 'plugin_config_hog_functions',
            loader: async (teamIds: string[]) => this.loadAndBuildHogFunctions(teamIds),
            refreshAgeMs: 600000, // 10 minutes
            refreshBackgroundAgeMs: 300000, // 5 minutes
            bufferMs: 10, // 10ms buffer for batching
        })
    }

    private async loadAndBuildHogFunctions(teamIds: string[]): Promise<Record<string, PluginConfigHogFunction[]>> {
        const { rows } = await this.hub.db.postgres.query(
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
        // Runs onEvent for all plugins for this team in parallel
        const pluginMethodsToRun = await this.getPluginMethodsForTeam(event.teamId, 'onEvent')

        const results = await Promise.all(
            pluginMethodsToRun.map(async ([pluginConfig, onEvent]) => {
                if (!this.pluginConfigsToSkipElementsParsing?.(pluginConfig.plugin_id)) {
                    // Elements parsing can be extremely slow, so we skip it for some plugins that are manually marked as not needing it
                    mutatePostIngestionEventWithElementsList(event)
                }

                const onEventPayload = convertToOnEventPayload(event)

                let error: any = null

                // Runs onEvent for a single plugin without any retries
                const timer = new Date()
                try {
                    // TODO: This is where we should proxy to the legacy plugin call
                    await onEvent(onEventPayload)
                } catch (e) {
                    error = e
                }

                pluginActionMsSummary
                    .labels(pluginConfig.plugin?.id.toString() ?? '?', 'onEvent', error ? 'error' : 'success')
                    .observe(new Date().getTime() - timer.getTime())

                return { pluginConfigId: pluginConfig.id, error }
            })
        )

        try {
            const invocations = await this.getLegacyPluginHogFunctionInvocations(invocation)

            if (invocations.length !== pluginMethodsToRun.length) {
                logger.warn('Legacy plugin hog function invocations count does not match plugin methods to run count', {
                    hog_function_invocations_count: invocations.length,
                    hog_function_invocations: invocations.map((invocation) => invocation.hogFunction.name).join(', '),
                    plugin_methods_to_run_count: pluginMethodsToRun.length,
                    plugin_names: pluginMethodsToRun.map(([pluginConfig]) => pluginConfig.plugin?.name).join(', '),
                    event_uuid: invocation.event.uuid,
                    team_id: invocation.project.id,
                })
                legacyPluginConfigComparisonCounter.labels('mismatch').inc()
            } else {
                legacyPluginConfigComparisonCounter.labels('match').inc()
            }

            if (!invocations.length) {
                return
            }

            // TODO: This will be how it is done in the future
            // for (const invocation of invocations) {
            //     await this.legacyPluginExecutor.execute(invocation)
            // }
        } catch (error: any) {
            logger.error('Error comparing plugin configs to hog functions', {
                error: error?.message,
            })
        }

        for (const { pluginConfigId, error } of results) {
            if (error) {
                void this.promiseScheduler.schedule(
                    this.hub.appMetrics.queueError(
                        {
                            teamId: event.teamId,
                            pluginConfigId,
                            category: 'onEvent',
                            failures: 1,
                        },
                        { error, event }
                    )
                )
            }
            void this.promiseScheduler.schedule(
                this.hub.appMetrics.queueMetric({
                    teamId: event.teamId,
                    pluginConfigId,
                    category: 'onEvent',
                    successes: 1,
                })
            )
        }

        vmFetchTracker.clearRequests()
        legacyFetchTracker.clearRequests()
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
        return await this.runWithHeartbeat(async () => {
            const events: HogFunctionInvocationGlobals[] = []

            await Promise.all(
                messages.map(async (message) => {
                    try {
                        const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                        const team = await this.hub.teamManager.getTeam(clickHouseEvent.team_id)

                        if (!team) {
                            return
                        }

                        const pluginConfigs = this.hub.pluginConfigsPerTeam.get(team.id) || []
                        if (pluginConfigs.length === 0) {
                            return
                        }

                        if (this.hub.CDP_LEGACY_EVENT_REDIRECT_TOPIC) {
                            void this.promiseScheduler.schedule(this.emitToReplicaTopic([message]))

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
        })
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

    private async getPluginMethodsForTeam<M extends keyof PluginMethodsConcrete>(
        teamId: number,
        method: M
    ): Promise<[PluginConfig, PluginMethodsConcrete[M]][]> {
        const pluginConfigs = this.hub.pluginConfigsPerTeam.get(teamId) || []
        if (pluginConfigs.length === 0) {
            return []
        }

        const methodsObtained = await Promise.all(
            pluginConfigs.map(async (pluginConfig) => [
                pluginConfig,
                await pluginConfig?.instance?.getPluginMethod(method),
            ])
        )

        const methodsObtainedFiltered = methodsObtained.filter(([_, method]) => !!method) as [
            PluginConfig,
            PluginMethodsConcrete[M],
        ][]

        return methodsObtainedFiltered
    }

    private async emitToReplicaTopic(kafkaMessages: Message[]) {
        const redirectTopic = this.hub.CDP_LEGACY_EVENT_REDIRECT_TOPIC
        if (!redirectTopic) {
            throw new Error('No redirect topic configured')
        }

        await Promise.all(
            kafkaMessages.map((message) => {
                return this.kafkaProducer!.produce({
                    topic: redirectTopic,
                    value: message.value,
                    key: message.key ?? null,
                    headers: parseKafkaHeaders(message.headers),
                })
            })
        )
    }
}

function mutatePostIngestionEventWithElementsList(event: PostIngestionEvent): void {
    if (event.elementsList) {
        // Don't set if already done before
        return
    }

    event.elementsList = event.properties['$elements_chain']
        ? chainToElements(event.properties['$elements_chain'], event.teamId)
        : []

    event.elementsList = event.elementsList.map((element) => ({
        ...element,
        attr_class: element.attributes?.attr__class ?? element.attr_class,
        $el_text: element.text,
    }))
}

function convertToOnEventPayload(event: PostIngestionEvent): ProcessedPluginEvent {
    return {
        distinct_id: event.distinctId,
        ip: null, // deprecated : within properties[$ip] now
        team_id: event.teamId,
        event: event.event,
        properties: event.properties,
        timestamp: event.timestamp,
        $set: event.properties.$set,
        $set_once: event.properties.$set_once,
        uuid: event.eventUuid,
        elements: event.elementsList ?? [],
    }
}
