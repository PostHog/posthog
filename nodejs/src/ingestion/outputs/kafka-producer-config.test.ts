import { hostname } from 'os'

import { AllowedConfigKey, getProducerConfig } from './kafka-producer-config'

const TEST_CONFIG_MAP: Partial<Record<AllowedConfigKey, string>> = {
    'metadata.broker.list': 'TEST_BROKER',
    'security.protocol': 'TEST_SECURITY_PROTOCOL',
    'compression.codec': 'TEST_COMPRESSION',
    'linger.ms': 'TEST_LINGER',
    'batch.size': 'TEST_BATCH_SIZE',
    'enable.ssl.certificate.verification': 'TEST_SSL_VERIFY',
}

describe('getProducerConfig', () => {
    const OLD_ENV = process.env

    beforeEach(() => {
        jest.resetModules()
        process.env = { ...OLD_ENV }
    })

    afterAll(() => {
        process.env = OLD_ENV
    })

    it('returns defaults when no env vars are set', () => {
        const config = getProducerConfig(TEST_CONFIG_MAP)

        expect(config).toEqual({
            'client.id': hostname(),
            'metadata.broker.list': 'kafka:9092',
            'compression.codec': 'snappy',
            'linger.ms': 20,
            'batch.size': 8 * 1024 * 1024,
            'queue.buffering.max.messages': 100_000,
            log_level: 4,
            'enable.idempotence': true,
            'metadata.max.age.ms': 30000,
            'retry.backoff.ms': 500,
            'socket.timeout.ms': 30000,
            'max.in.flight.requests.per.connection': 5,
        })
    })

    it('overrides defaults with env vars', () => {
        process.env.TEST_BROKER = 'broker1:9092,broker2:9092'
        process.env.TEST_COMPRESSION = 'gzip'
        process.env.TEST_LINGER = '50'

        const config = getProducerConfig(TEST_CONFIG_MAP)

        expect(config['metadata.broker.list']).toBe('broker1:9092,broker2:9092')
        expect(config['compression.codec']).toBe('gzip')
        expect(config['linger.ms']).toBe(50)
    })

    it('coerces numeric values', () => {
        process.env.TEST_LINGER = '100'
        process.env.TEST_BATCH_SIZE = '4194304'

        const config = getProducerConfig(TEST_CONFIG_MAP)

        expect(config['linger.ms']).toBe(100)
        expect(config['batch.size']).toBe(4194304)
    })

    it('parses boolean values', () => {
        process.env.TEST_SSL_VERIFY = 'false'

        const config = getProducerConfig(TEST_CONFIG_MAP)

        expect(config['enable.ssl.certificate.verification']).toBe(false)
    })

    it('throws on invalid enum values', () => {
        process.env.TEST_SECURITY_PROTOCOL = 'invalid_protocol'

        expect(() => getProducerConfig(TEST_CONFIG_MAP)).toThrow()
    })

    it('throws on invalid boolean values', () => {
        process.env.TEST_SSL_VERIFY = 'maybe'

        expect(() => getProducerConfig(TEST_CONFIG_MAP)).toThrow()
    })

    it('always sets client.id to hostname', () => {
        const config = getProducerConfig(TEST_CONFIG_MAP)

        expect(config['client.id']).toBe(hostname())
    })

    it('ignores env vars not in the config map', () => {
        process.env.TEST_UNKNOWN_SETTING = 'value'

        const config = getProducerConfig(TEST_CONFIG_MAP)

        expect(config).not.toHaveProperty('unknown.setting')
    })
})
