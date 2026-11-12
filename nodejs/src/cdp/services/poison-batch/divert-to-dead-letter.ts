import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { ProducerMessage } from '~/common/kafka/producer'

import { DEAD_LETTER_QUEUE } from '../../types'
import { cyclotronTopic } from '../job-queue/job-queue-kafka'
import { SetAside } from './crash-guard'

const messagesDiverted = new Counter({
    name: 'cdp_batch_diverted_messages_total',
    help: 'Messages of a diverted batch that reached the dead letter topic.',
    labelNames: ['group'],
})

/**
 * The crash guard's set aside for the hog worker. It produces the messages of a flagged partition unchanged
 * to the dead letter topic, where the dead letter worker sorts the poisoned messages from the healthy ones.
 * When one produce fails, the set aside rejects and the replay produces every message again, including the
 * ones that already reached the topic, so a healthy message can run twice.
 */
export function divertToDeadLetter(produce: (message: ProducerMessage) => Promise<void>, group: string): SetAside {
    return async (messages: Message[]): Promise<void> => {
        await Promise.all(
            messages.map((message) =>
                produce({
                    topic: cyclotronTopic(DEAD_LETTER_QUEUE),
                    key: message.key ?? null,
                    value: message.value,
                    headers: parseKafkaHeaders(message.headers),
                })
            )
        )
        messagesDiverted.labels(group).inc(messages.length)
    }
}
