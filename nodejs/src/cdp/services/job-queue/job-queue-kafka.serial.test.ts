import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobQueueKafka } from './job-queue-kafka'

describe('CyclotronJobQueueKafka on Kafka', () => {
    jest.setTimeout(10_000)

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('lets two consumers that share the queue stop its producer at the same time', async () => {
        const created = jest.spyOn(KafkaProducerWrapper, 'create')
        const queue = new CyclotronJobQueueKafka(
            undefined,
            {
                CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: false,
                CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
                ENCRYPTION_SALT_KEYS: '',
            },
            10
        )
        await queue.startAsProducer()
        const producer = await created.mock.results[0].value
        await queue.queueInvocations([createExampleInvocation({}, {}, 'hog')])
        await producer.checkConnection(2_000)

        await Promise.all([queue.stopProducer(), queue.stopProducer()])

        await expect(producer.checkConnection(2_000)).rejects.toThrow()
        await expect(queue.queueInvocations([createExampleInvocation({}, {}, 'hog')])).rejects.toThrow()
    })
})
