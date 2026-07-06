import { ConsumerGlobalConfig } from 'node-rdkafka'

import { getKafkaConfigFromEnv, stripClassicProtocolConfig } from './config'

describe('getKafkaConfigFromEnv', () => {
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

        const config = getKafkaConfigFromEnv('PRODUCER')

        expect(config).toMatchInlineSnapshot(`
            {
              "compression.type": "gzip",
              "enable.idempotence": false,
              "queue.buffering.max.ms": 1000,
            }
        `)
    })

    it('ignores env vars that do not start with its prefix', () => {
        process.env.KAFKA_CONSUMER_GROUP_ID = 'test-group'
        process.env.KAFKA_PRODUCER_COMPRESSION_TYPE = 'gzip'

        expect(getKafkaConfigFromEnv('PRODUCER')).toMatchInlineSnapshot(`
            {
              "compression.type": "gzip",
            }
        `)
        expect(getKafkaConfigFromEnv('CONSUMER')).toMatchInlineSnapshot(`
            {
              "group.id": "test-group",
            }
        `)
        expect(getKafkaConfigFromEnv('CDP_PRODUCER')).toMatchInlineSnapshot(`{}`)
    })

    it('ignores empty values', () => {
        process.env.KAFKA_PRODUCER_COMPRESSION_TYPE = ''
        process.env.KAFKA_PRODUCER_VALID_SETTING = 'value'

        const config = getKafkaConfigFromEnv('PRODUCER')

        expect(config).toMatchInlineSnapshot(`
            {
              "valid.setting": "value",
            }
        `)
    })
})

describe('stripClassicProtocolConfig', () => {
    it('leaves config untouched for the classic protocol', () => {
        const config: ConsumerGlobalConfig = {
            'group.id': 'test-group',
            'session.timeout.ms': 30_000,
            'partition.assignment.strategy': 'cooperative-sticky',
        }

        expect(stripClassicProtocolConfig(config)).toEqual(config)
    })

    it('strips classic-only keys when group.protocol is consumer', () => {
        const config: ConsumerGlobalConfig = {
            'group.id': 'test-group',
            'group.protocol': 'consumer',
            'session.timeout.ms': 30_000,
            'heartbeat.interval.ms': 3_000,
            'partition.assignment.strategy': 'cooperative-sticky',
            'group.protocol.type': 'consumer',
            'max.poll.interval.ms': 300_000,
        }

        expect(stripClassicProtocolConfig(config)).toEqual({
            'group.id': 'test-group',
            'group.protocol': 'consumer',
            'max.poll.interval.ms': 300_000,
        })
    })

    it('does not mutate the input config', () => {
        const config: ConsumerGlobalConfig = {
            'group.protocol': 'consumer',
            'session.timeout.ms': 30_000,
        }

        stripClassicProtocolConfig(config)

        expect(config['session.timeout.ms']).toBe(30_000)
    })
})
