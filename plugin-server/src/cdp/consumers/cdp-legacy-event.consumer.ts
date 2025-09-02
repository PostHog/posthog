import { Message } from 'node-rdkafka'

import { instrumented } from '~/common/tracing/tracing-utils'

import { parseKafkaHeaders } from '../../kafka/consumer'
import { Hub, ISOTimestamp, PostIngestionEvent, ProjectId, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { runOnEvent } from '../../worker/plugins/run'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpEventsConsumer, counterParseError } from './cdp-events.consumer'

/**
 * This is a temporary consumer that hooks into the existing onevent consumer group
 * It currently just runs the same logic as the old one but with noderdkafka as the consumer tech which should improve things
 * We can then use this to gradually move over to the new hog functions
 */
export class CdpLegacyEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpLegacyEventsConsumer'
    protected promiseScheduler = new PromiseScheduler()

    constructor(hub: Hub) {
        super(hub, hub.CDP_LEGACY_EVENT_CONSUMER_TOPIC, hub.CDP_LEGACY_EVENT_CONSUMER_GROUP_ID)

        logger.info('🔁', `CdpLegacyEventsConsumer setup`, {
            pluginConfigs: Array.from(this.hub.pluginConfigsPerTeam.keys()),
        })
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

        return await runOnEvent(this.hub, event)
    }

    @instrumented('cdpLegacyEventsConsumer.processBatch')
    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (invocationGlobals.length) {
            const results = await Promise.all(invocationGlobals.map((x) => this.processEvent(x)))

            // Schedule the background work
            for (const subtasks of results) {
                for (const { backgroundTask } of subtasks) {
                    void this.promiseScheduler.schedule(backgroundTask)
                }
            }
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
