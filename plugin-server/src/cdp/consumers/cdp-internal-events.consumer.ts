import { Message } from 'node-rdkafka'

import { KAFKA_CDP_INTERNAL_EVENTS } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { status } from '../../utils/status'
import { counterParseError } from '../metrics/metrics'
import { CdpInternalEventSchema } from '../schema'
import { HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { convertInternalEventToHogFunctionInvocationGlobals } from '../utils'
import { CdpProcessedEventsConsumer } from './cdp-processed-events.consumer'

/**
 * This consumer handles incoming events from the main clickhouse topic
 * Currently it produces to both kafka and Cyclotron based on the team
 */
export class CdpInternalEventsConsumer extends CdpProcessedEventsConsumer {
    protected name = 'CdpInternalEventsConsumer'
    protected topic = KAFKA_CDP_INTERNAL_EVENTS
    protected groupId = 'cdp-internal-events-consumer'
    protected hogTypes: HogFunctionTypeType[] = ['internal_destination']

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
                                const kafkaEvent = JSON.parse(message.value!.toString()) as unknown
                                // This is the input stream from elsewhere so we want to do some proper validation
                                const event = CdpInternalEventSchema.parse(kafkaEvent)

                                if (!this.hogFunctionManager.teamHasHogDestinations(event.team_id)) {
                                    // No need to continue if the team doesn't have any functions
                                    return
                                }

                                const team = await this.hub.teamManager.fetchTeam(event.team_id)
                                if (!team) {
                                    return
                                }
                                events.push(
                                    convertInternalEventToHogFunctionInvocationGlobals(
                                        event,
                                        team,
                                        this.hub.SITE_URL ?? 'http://localhost:8000'
                                    )
                                )
                            } catch (e) {
                                status.error('Error parsing message', e)
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
