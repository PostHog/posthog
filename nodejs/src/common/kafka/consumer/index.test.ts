import { createKafkaConsumer } from '.'

import { defaultConfig } from '~/common/config/config'
import { logger } from '~/common/utils/logger'

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
    const originalBatchSizeKb = defaultConfig.CONSUMER_BATCH_SIZE_KB

    afterEach(() => {
        defaultConfig.CONSUMER_USE_V2 = original
        defaultConfig.CONSUMER_BATCH_SIZE_KB = originalBatchSizeKb
        jest.restoreAllMocks()
    })

    it.each([
        { useV2: false, batchSizeKb: 256, warns: true },
        { useV2: false, batchSizeKb: 0, warns: false },
        { useV2: true, batchSizeKb: 256, warns: false },
    ])(
        'warns that v1 ignores the byte bound: $warns with CONSUMER_USE_V2=$useV2 and CONSUMER_BATCH_SIZE_KB=$batchSizeKb',
        ({ useV2, batchSizeKb, warns }) => {
            defaultConfig.CONSUMER_USE_V2 = useV2
            defaultConfig.CONSUMER_BATCH_SIZE_KB = batchSizeKb
            const warn = jest.spyOn(logger, 'warn')

            createKafkaConsumer({ groupId: 'my-group', topic: 'my-topic' })

            const byteBoundWarnings = warn.mock.calls.filter(
                ([, message]) => message === 'kafka_consumer_factory_batch_byte_bound_ignored_by_v1'
            )
            expect(byteBoundWarnings).toHaveLength(warns ? 1 : 0)
        }
    )

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
