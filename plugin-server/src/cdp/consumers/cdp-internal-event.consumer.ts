import { Message } from 'node-rdkafka'

import { KAFKA_CDP_INTERNAL_EVENTS } from '../../config/kafka-topics'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
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
            this.runInstrumented('handleEachBatch.parseKafkaMessages', async () => {
                const events: HogFunctionInvocationGlobals[] = []
                await Promise.all(
                    messages.map(async (message) => {
                        try {
                            const kafkaEvent = parseJSON(message.value!.toString()) as unknown
                            // This is the input stream from elsewhere so we want to do some proper validation
                            const event = CdpInternalEventSchema.parse(kafkaEvent)

                            const [teamHogFunctions, team] = await Promise.all([
                                this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, ['internal_destination']),
                                this.hub.teamManager.fetchTeam(event.team_id),
                            ])

                            if (!teamHogFunctions.length || !team) {
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
                            logger.error('Error parsing message', e)
                            counterParseError.labels({ error: e.message }).inc()
                        }
                    })
                )

                return events
            })
        )
    }
}
