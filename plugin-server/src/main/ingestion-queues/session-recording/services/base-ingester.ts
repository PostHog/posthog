import { HighLevelProducer as RdKafkaProducer, NumberNullUndefined } from 'node-rdkafka'

import { findOffsetsToCommit } from '../../../../kafka/consumer'
import { retryOnDependencyUnavailableError } from '../../../../kafka/error-handling'
import { flushProducer } from '../../../../kafka/producer'
import { status } from '../../../../utils/status'
import { eventDroppedCounter } from '../../metrics'
import { IncomingRecordingMessage } from '../types'
import { OffsetHighWaterMarker } from './offset-high-water-marker'

export abstract class BaseIngester {
    protected constructor(
        protected readonly label: string,
        protected readonly producer: RdKafkaProducer,
        protected readonly persistentHighWaterMarker?: OffsetHighWaterMarker
    ) {}

    protected drop = (reason: string) => {
        eventDroppedCounter
            .labels({
                event_type: this.label,
                drop_cause: reason,
            })
            .inc()
    }

    public async consumeBatch(messages: IncomingRecordingMessage[]) {
        const pendingProduceRequests: Promise<NumberNullUndefined>[] = []

        for (const message of messages) {
            const results = await retryOnDependencyUnavailableError(() => this.consume(message))
            if (results) {
                pendingProduceRequests.push(...results)
            }
        }

        // On each loop, we flush the producer to ensure that all messages
        // are sent to Kafka.
        try {
            await flushProducer(this.producer!)
        } catch (error) {
            // Rather than handling errors from flush, we instead handle
            // errors per produce request, which gives us a little more
            // flexibility in terms of deciding if it is a terminal
            // error or not.
        }

        // We wait on all the produce requests to complete. After the
        // flush they should all have been resolved/rejected already. If
        // we get an intermittent error, such as a Kafka broker being
        // unavailable, we will throw. We are relying on the Producer
        // already having handled retries internally.
        for (const produceRequest of pendingProduceRequests) {
            try {
                await produceRequest
            } catch (error) {
                status.error('🔁', `[${this.label}] main_loop_error`, { error })

                if (error?.isRetriable) {
                    // We assume that the error is retriable, then we
                    // are probably in a state where e.g. Kafka is down
                    // temporarily, and we would rather simply throw and
                    // have the process restarted.
                    throw error
                }
            }
        }

        if (this.persistentHighWaterMarker) {
            const topicPartitionOffsets = findOffsetsToCommit(
                messages.map((message) => ({
                    topic: message.metadata.topic,
                    partition: message.metadata.partition,
                    offset: message.metadata.highOffset,
                }))
            )

            await Promise.all(
                topicPartitionOffsets.map((tpo) => this.persistentHighWaterMarker!.add(tpo, this.label, tpo.offset))
            )
        }
    }

    public abstract consume(event: IncomingRecordingMessage): Promise<Promise<number | null | undefined>[] | void>
}
