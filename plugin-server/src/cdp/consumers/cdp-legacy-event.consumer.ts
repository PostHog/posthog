import { Message } from 'node-rdkafka'

import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { instrumented } from '~/common/tracing/tracing-utils'
import { buildIntegerMatcher } from '~/config/config'
import { chainToElements } from '~/utils/db/elements-chain'
import { pluginActionMsSummary } from '~/worker/metrics'

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
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpEventsConsumer } from './cdp-events.consumer'
import { counterParseError } from './metrics'

/**
 * This is a temporary consumer that hooks into the existing onevent consumer group
 * It currently just runs the same logic as the old one but with noderdkafka as the consumer tech which should improve things
 * We can then use this to gradually move over to the new hog functions
 */
export class CdpLegacyEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpLegacyEventsConsumer'
    protected promiseScheduler = new PromiseScheduler()

    private pluginConfigsToSkipElementsParsing: ValueMatcher<number>

    constructor(hub: Hub) {
        super(hub, hub.CDP_LEGACY_EVENT_CONSUMER_TOPIC, hub.CDP_LEGACY_EVENT_CONSUMER_GROUP_ID)

        logger.info('🔁', `CdpLegacyEventsConsumer setup`, {
            pluginConfigs: Array.from(this.hub.pluginConfigsPerTeam.keys()),
        })

        this.pluginConfigsToSkipElementsParsing = buildIntegerMatcher(process.env.SKIP_ELEMENTS_PARSING_PLUGINS, true)
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

        await Promise.all(
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

                if (error) {
                    void this.promiseScheduler.schedule(
                        this.hub.appMetrics.queueError(
                            {
                                teamId: event.teamId,
                                pluginConfigId: pluginConfig.id,
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
                        pluginConfigId: pluginConfig.id,
                        category: 'onEvent',
                        successes: 1,
                    })
                )
            })
        )
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
