import { getProducerConfigFromEnv } from './config'

describe('getProducerConfigFromEnv', () => {
    const OLD_ENV = process.env

    beforeEach(() => {
        jest.resetModules()
        process.env = { ...OLD_ENV }
    })

    afterAll(() => {
        process.env = OLD_ENV
    })

    it('converts KAFKA_PRODUCER_ env vars to rdkafka config', () => {
        process.env.KAFKA_PRODUCER_COMPRESSION_TYPE = 'gzip'
        process.env.KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MS = '1000'
        process.env.KAFKA_PRODUCER_ENABLE_IDEMPOTENCE = 'false'

        const config = getProducerConfigFromEnv()

        expect(config).toEqual({
            'compression.type': 'gzip',
            'queue.buffering.max.ms': 1000,
            'enable.idempotence': false,
        })
    })

    it('ignores env vars that do not start with KAFKA_PRODUCER_', () => {
        process.env.KAFKA_CONSUMER_GROUP_ID = 'test-group'
        process.env.KAFKA_PRODUCER_COMPRESSION_TYPE = 'gzip'

        const config = getProducerConfigFromEnv()

        expect(config).toEqual({
            'compression.type': 'gzip',
        })
    })

    it('ignores empty values', () => {
        process.env.KAFKA_PRODUCER_COMPRESSION_TYPE = ''
        process.env.KAFKA_PRODUCER_VALID_SETTING = 'value'

        const config = getProducerConfigFromEnv()

        expect(config).toEqual({
            'valid.setting': 'value',
        })
    })

    it('does not override keys that exist in defaultConfig', () => {
        // Add a mock value to defaultConfig
        const mockKey = 'KAFKA_PRODUCER_HOSTS'
        process.env[mockKey] = 'env-value'

        const config = getProducerConfigFromEnv()

        expect(config).toEqual({})
    })
})
