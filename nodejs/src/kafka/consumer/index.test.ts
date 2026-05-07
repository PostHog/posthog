import { createKafkaConsumer } from '.'

import { defaultConfig } from '~/config/config'

import { KafkaConsumer } from './consumer-v1'
import { KafkaConsumerV2 } from './consumer-v2'

jest.mock('../admin', () => ({ ensureTopicExists: jest.fn().mockResolvedValue(undefined) }))
jest.mock('node-rdkafka', () => ({
    KafkaConsumer: jest.fn().mockImplementation(() => ({
        connect: jest.fn(),
        subscribe: jest.fn(),
        on: jest.fn(),
        isConnected: jest.fn().mockReturnValue(false),
        disconnect: jest.fn().mockImplementation((cb) => cb && cb(null)),
        setDefaultConsumeTimeout: jest.fn(),
        assignments: jest.fn().mockReturnValue([]),
    })),
    CODES: { ERRORS: { ERR__REVOKE_PARTITIONS: -174, ERR__ASSIGN_PARTITIONS: -175 } },
}))

describe('createKafkaConsumer', () => {
    const original = defaultConfig.CONSUMER_USE_V2

    afterEach(() => {
        defaultConfig.CONSUMER_USE_V2 = original
    })

    it('returns v1 when CONSUMER_USE_V2 is false', () => {
        defaultConfig.CONSUMER_USE_V2 = false
        const c = createKafkaConsumer({ groupId: 'my-group', topic: 'my-topic' })
        expect(c).toBeInstanceOf(KafkaConsumer)
    })

    it('returns v2 when CONSUMER_USE_V2 is true', () => {
        defaultConfig.CONSUMER_USE_V2 = true
        const c = createKafkaConsumer({ groupId: 'my-group', topic: 'my-topic' })
        expect(c).toBeInstanceOf(KafkaConsumerV2)
    })
})
