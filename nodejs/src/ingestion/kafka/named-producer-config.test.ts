import { getNamedProducerConfig, hasNamedProducerConfig } from './named-producer-config'

describe('named-producer-config', () => {
    const OLD_ENV = process.env

    beforeEach(() => {
        jest.resetModules()
        process.env = { ...OLD_ENV }
    })

    afterAll(() => {
        process.env = OLD_ENV
    })

    describe('getNamedProducerConfig', () => {
        it('parses INGESTION_KAFKA_PRODUCER_{NAME}_* env vars to rdkafka config', () => {
            process.env.INGESTION_KAFKA_PRODUCER_MSK_METADATA_BROKER_LIST = 'broker1:9092,broker2:9092'
            process.env.INGESTION_KAFKA_PRODUCER_MSK_SECURITY_PROTOCOL = 'SSL'
            process.env.INGESTION_KAFKA_PRODUCER_MSK_COMPRESSION_CODEC = 'snappy'

            const config = getNamedProducerConfig('MSK')

            expect(config).toEqual({
                'metadata.broker.list': 'broker1:9092,broker2:9092',
                'security.protocol': 'SSL',
                'compression.codec': 'snappy',
            })
        })

        it('is case-insensitive on the name', () => {
            process.env.INGESTION_KAFKA_PRODUCER_MSK_SECURITY_PROTOCOL = 'SSL'

            expect(getNamedProducerConfig('msk')).toEqual({
                'security.protocol': 'SSL',
            })
        })

        it('does not pick up env vars for a different producer name', () => {
            process.env.INGESTION_KAFKA_PRODUCER_MSK_METADATA_BROKER_LIST = 'msk:9092'
            process.env.INGESTION_KAFKA_PRODUCER_WARPSTREAM_METADATA_BROKER_LIST = 'ws:9092'

            const mskConfig = getNamedProducerConfig('MSK')
            const wsConfig = getNamedProducerConfig('WARPSTREAM')

            expect(mskConfig).toEqual({ 'metadata.broker.list': 'msk:9092' })
            expect(wsConfig).toEqual({ 'metadata.broker.list': 'ws:9092' })
        })

        it('coerces numeric values', () => {
            process.env.INGESTION_KAFKA_PRODUCER_TEST_LINGER_MS = '50'

            expect(getNamedProducerConfig('TEST')).toEqual({ 'linger.ms': 50 })
        })

        it('coerces boolean values', () => {
            process.env.INGESTION_KAFKA_PRODUCER_TEST_ENABLE_IDEMPOTENCE = 'true'

            expect(getNamedProducerConfig('TEST')).toEqual({ 'enable.idempotence': true })
        })

        it('returns empty object when no matching env vars exist', () => {
            expect(getNamedProducerConfig('NONEXISTENT')).toEqual({})
        })
    })

    describe('hasNamedProducerConfig', () => {
        it('returns true when env vars exist for the name', () => {
            process.env.INGESTION_KAFKA_PRODUCER_MSK_METADATA_BROKER_LIST = 'broker:9092'

            expect(hasNamedProducerConfig('MSK')).toBe(true)
        })

        it('returns false when no env vars exist for the name', () => {
            expect(hasNamedProducerConfig('NONEXISTENT')).toBe(false)
        })

        it('is case-insensitive', () => {
            process.env.INGESTION_KAFKA_PRODUCER_MSK_METADATA_BROKER_LIST = 'broker:9092'

            expect(hasNamedProducerConfig('msk')).toBe(true)
        })
    })
})
