import { KafkaConsumer as RdKafkaConsumer, Message } from 'node-rdkafka'

import { waitForExpect } from '~/tests/helpers/expectations'

import { KafkaConsumer } from './consumer'

jest.mock('./admin', () => ({
    ensureTopicExists: jest.fn().mockResolvedValue(undefined),
}))

jest.mock('node-rdkafka', () => ({
    KafkaConsumer: jest.fn().mockImplementation(() => ({
        connect: jest.fn().mockImplementation((_, cb) => cb(null)),
        subscribe: jest.fn(),
        consume: jest.fn().mockImplementation((_, cb) => cb(null, [])),
        disconnect: jest.fn().mockImplementation((cb) => cb(null)),
        isConnected: jest.fn().mockReturnValue(true),
        on: jest.fn(),
        assignments: jest.fn().mockReturnValue([]),
        offsetsStore: jest.fn(),
        setDefaultConsumeTimeout: jest.fn(),
    })),
}))

const createKafkaMessage = (message: Partial<Message> = {}): Message => ({
    value: Buffer.from('test-value'),
    key: Buffer.from('test-key'),
    offset: 1,
    partition: 0,
    topic: 'test-topic',
    size: 10,
    ...message,
})

jest.setTimeout(3000)

describe('consumer', () => {
    let consumer: KafkaConsumer
    let mockRdKafkaConsumer: jest.Mocked<RdKafkaConsumer>

    beforeEach(() => {
        consumer = new KafkaConsumer({
            groupId: 'test-group',
            topic: 'test-topic',
        })

        mockRdKafkaConsumer = jest.mocked(consumer['rdKafkaConsumer'])

        // @ts-expect-error mock implementation
        mockRdKafkaConsumer.consume.mockImplementation((_, cb) => {
            setTimeout(() => {
                cb(null, [createKafkaMessage()])
            }, 1)
        })
    })

    afterEach(async () => {
        console.log('afterEach')
        if (consumer) {
            await consumer.disconnect()
        }
    })

    it('should create a consumer with correct config', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await consumer.connect(eachBatch)
        expect(mockRdKafkaConsumer.connect).toHaveBeenCalled()
        expect(mockRdKafkaConsumer.subscribe).toHaveBeenCalledWith(['test-topic'])

        await waitForExpect(() => {
            expect(eachBatch).toHaveBeenCalled()
        }, 500)

        expect(eachBatch).toHaveBeenCalledWith([createKafkaMessage()])
    })
})
