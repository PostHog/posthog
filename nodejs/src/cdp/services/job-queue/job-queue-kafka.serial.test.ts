import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobQueueKafka } from './job-queue-kafka'

describe('CyclotronJobQueueKafka on Kafka', () => {
    jest.setTimeout(10_000)

    it('lets two consumers that share the queue stop its producer at the same time', async () => {
        const queue = new CyclotronJobQueueKafka(
            undefined,
            { CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: false, CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '' },
            10
        )
        await queue.startAsProducer()
        await queue.queueInvocations([createExampleInvocation({}, {}, 'hog')])
        const producer = queue['kafkaProducer']!
        await producer.checkConnection(2_000)

        await Promise.all([queue.stopProducer(), queue.stopProducer()])

        await expect(producer.checkConnection(2_000)).rejects.toThrow()
        await expect(queue.queueInvocations([createExampleInvocation({}, {}, 'hog')])).rejects.toThrow()
    })
})
