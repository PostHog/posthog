import { Message } from 'node-rdkafka'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, ISOTimestamp, PostIngestionEvent, ProjectId, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { runOnEvent } from '../../worker/plugins/run'
import { HogFunctionInvocation, HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpEventsConsumer, counterParseError } from './cdp-events.consumer'

/**
 * This is a temporary consumer that hooks into the existing onevent consumer group
 * It currently just runs the same logic as the old one but with noderdkafka as the consumer tech which should improve things
 * We can then use this to gradually move over to the new hog functions
 */
export class CdpLegacyEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpLegacyEventsConsumer'

    constructor(hub: Hub) {
        super(hub, KAFKA_EVENTS_JSON, 'clickhouse-plugin-server-async-onevent')

        logger.info('🔁', `CdpLegacyEventsConsumer setup`, {
            pluginConfigs: Array.from(this.hub.pluginConfigsPerTeam.keys()),
        })
    }

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

        await runOnEvent(this.hub, event)
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: HogFunctionInvocation[] }> {
        if (!invocationGlobals.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        await Promise.all(
            invocationGlobals.map((x) => {
                return this.runInstrumented('cdpLegacyEventsConsumer.processEvent', () => this.processEvent(x))
            })
        )

        // NOTE: We _could_ consider moving this to a background task to improve throughput with a max concurrency of 2 for example
        // but we should avoid it if possible

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.resolve(),
            invocations: [],
        }
    }

    // This consumer always parses from kafka
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => {
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
                                events.push(
                                    convertToHogFunctionInvocationGlobals(
                                        clickHouseEvent,
                                        team,
                                        this.hub.SITE_URL ?? 'http://localhost:8000'
                                    )
                                )
                            } catch (e) {
                                logger.error('Error parsing message', e)
                                counterParseError.labels({ error: e.message }).inc()
                            }
                        })
                    )

                    return events
                },
            })
        )
    }
}
