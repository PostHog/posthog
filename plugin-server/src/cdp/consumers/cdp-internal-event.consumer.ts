import { Message } from 'node-rdkafka'

import { KAFKA_CDP_INTERNAL_EVENTS } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../utils/instrument'
import { status } from '../../utils/status'
import { CdpInternalEventSchema } from '../schema'
import { HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { convertInternalEventToHogFunctionInvocationGlobals } from '../utils'
import { counterParseError } from './cdp-base.consumer'
import { CdpProcessedEventsConsumer } from './cdp-processed-events.consumer'

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
                    const parsedMessages = messages.reduce((acc, message) => {
                        try {
                            const kafkaEvent = JSON.parse(message.value!.toString()) as unknown
                            // This is the input stream from elsewhere so we want to do some proper validation
                            const event = CdpInternalEventSchema.parse(kafkaEvent)

                            if (!this.hogFunctionManager.teamHasHogDestinations(event.team_id)) {
                                // No need to continue if the team doesn't have any functions
                                return acc
                            }

                            return [...acc, event]
                        } catch (e) {
                            status.error('Error parsing message', e)
                            counterParseError.labels({ error: e.message }).inc()
                        }

                        return acc
                    }, [] as ReturnType<typeof CdpInternalEventSchema.parse>[])

                    const teams = (
                        await this.hub.teamManager.getTeams(
                            [],
                            parsedMessages.map((x) => x.team_id)
                        )
                    ).byId

                    const events = parsedMessages.reduce((acc, event) => {
                        const team = teams[event.team_id]
                        if (!team) {
                            return acc
                        }

                        return [
                            ...acc,
                            convertInternalEventToHogFunctionInvocationGlobals(
                                event,
                                team,
                                this.hub.SITE_URL ?? 'http://localhost:8000'
                            ),
                        ]
                    }, [] as HogFunctionInvocationGlobals[])

                    return events
                },
            })
        )
    }
}
