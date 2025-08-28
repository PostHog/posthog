import { Message } from 'node-rdkafka'

import { instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_CDP_INTERNAL_EVENTS } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpInternalEventSchema } from '../schema'
import { HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { convertInternalEventToHogFunctionInvocationGlobals } from '../utils'
import { CdpEventsConsumer, counterParseError } from './cdp-events.consumer'

export class CdpInternalEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpInternalEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['internal_destination']

    constructor(hub: Hub) {
        super(hub, KAFKA_CDP_INTERNAL_EVENTS, 'cdp-internal-events-consumer')
    }

    // This consumer always parses from kafka
    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.runWithHeartbeat(async () => {
            const events: HogFunctionInvocationGlobals[] = []
            await Promise.all(
                messages.map(async (message) => {
                    try {
                        const kafkaEvent = parseJSON(message.value!.toString()) as unknown
                        // This is the input stream from elsewhere so we want to do some proper validation
                        const event = CdpInternalEventSchema.parse(kafkaEvent)

                        const [teamHogFunctions, team] = await Promise.all([
                            this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, ['internal_destination']),
                            this.hub.teamManager.getTeam(event.team_id),
                        ])

                        if (!teamHogFunctions.length || !team) {
                            return
                        }

                        events.push(convertInternalEventToHogFunctionInvocationGlobals(event, team, this.hub.SITE_URL))
                    } catch (e) {
                        logger.error('Error parsing message', e)
                        counterParseError.labels({ error: e.message }).inc()
                    }
                })
            )

            return events
        })
    }
}
