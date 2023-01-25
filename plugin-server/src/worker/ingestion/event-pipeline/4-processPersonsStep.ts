import { PluginEvent } from '@posthog/plugin-scaffold'
import { KafkaJSError } from 'kafkajs'

import { KAFKA_BUFFER } from '../../../config/kafka-topics'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { normalizeEvent } from '../../../utils/event'
import { LazyPersonContainer } from '../lazy-person-container'
import { updatePersonState, updatePersonStateExceptProperties } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    const event = normalizeEvent(pluginEvent)

    const timestamp = parseEventTimestamp(event)

    if (runner.onlyUpdatePersonIdAssociations) {
        // If we're not performing all the processing, we need to send the event
        // to the buffer queue. Further processing will happen after the delay
        // has taken effect.
        //
        // We also need to ensure that we create any new persons and
        // distinct_ids, such that events in the delay window can denormalize
        // the person_id correctly.
        await updatePersonStateExceptProperties(
            event,
            event.team_id,
            String(event.distinct_id),
            timestamp,
            runner.hub.db,
            runner.hub.statsd,
            runner.hub.personManager,
            personContainer
        )

        const processEventAt = Date.now() + runner.hub.BUFFER_CONVERSION_SECONDS * 1000

        // NOTE: here we do not use the wrapper, as we want to ensure that if
        // the message is not send successfully to the Kafka topic for a
        // retriable error then this is raised up to the KafkaJS library,
        // preventing offsets from being committed.
        //
        // TODO: if throughput is an issue here, we can consider batching these
        // messages.
        try {
            await runner.hub.kafkaProducer.producer.send({
                topic: KAFKA_BUFFER,
                messages: [
                    {
                        key: event.distinct_id,
                        value: JSON.stringify(event),
                        headers: { processEventAt: processEventAt.toString(), eventId: event.uuid },
                    },
                ],
            })
        } catch (error) {
            runner.hub.statsd?.increment('kafka_buffer_produce_error', 1, [`error: ${error.name}`])
            if (error instanceof KafkaJSError) {
                // If the error is retriable, we want to raise it up to the
                // KafkaJS library, which will retry processing the message and
                // importantly not commit the offsets.
                if (error.retriable) {
                    throw new DependencyUnavailableError('Kafka buffer topic is unavailable', 'kafka', error)
                }
            }

            throw error
        }

        return null // Make sure we don't continue processing in this case.
    } else {
        // The runner can be configured to either update only and create persons
        // and distinct_id, or also update person properties and send the event
        // to ClickHouse. This is to make is possible to provide a delay before
        // person_id is denormalized onto the event.
        //
        // Here we are in the fullyProcessEvent mode, so we update the person
        // properties as well, and then continue to the next step.

        const newPersonContainer: LazyPersonContainer = await updatePersonState(
            event,
            event.team_id,
            String(event.distinct_id),
            timestamp,
            runner.hub.db,
            runner.hub.statsd,
            runner.hub.personManager,
            personContainer
        )

        return runner.nextStep('prepareEventStep', event, newPersonContainer)
    }
}
