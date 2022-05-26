import { Consumer } from 'kafkajs'

import { KAFKA_HEALTHCHECK } from '../../src/config/kafka-topics'
import { kafkaHealthcheck, setupKafkaHealthcheckConsumer } from '../../src/main/utils'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { resetKafka } from '../helpers/kafka'

jest.mock('kafkajs/src/loggers/console')
jest.mock('../../src/utils/status')
jest.setTimeout(70000) // 60 sec timeout

describe('kafka health check', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let statsd: any
    let consumer: Consumer

    beforeAll(async () => {
        await resetKafka()
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        statsd = {
            timing: jest.fn(),
        }
        consumer = await setupKafkaHealthcheckConsumer(hub.kafka!)
        await consumer.connect()
        consumer.pause([{ topic: KAFKA_HEALTHCHECK }])
    })

    afterEach(async () => {
        await consumer.disconnect()
        await closeHub()
    })

    // if kafka is up and running it should pass this healthcheck
    test('healthcheck passes under normal conditions', async () => {
        const [kafkaHealthy, error] = await kafkaHealthcheck(hub!.kafkaProducer, consumer, statsd, 5000)
        expect(kafkaHealthy).toEqual(true)
        expect(error).toEqual(null)
    })

    test('healthcheck fails if producer throws', async () => {
        hub!.kafkaProducer.flush = jest.fn(() => {
            throw new Error('producer error')
        })

        const [kafkaHealthy, error] = await kafkaHealthcheck(hub!.kafkaProducer, consumer, statsd, 5000)
        expect(kafkaHealthy).toEqual(false)
        expect(error!.message).toEqual('producer error')
        expect(statsd.timing).not.toHaveBeenCalled()

        jest.mocked(hub!.kafkaProducer.flush).mockReset()
    })

    test('healthcheck fails if consumer throws', async () => {
        consumer.resume = jest.fn(() => {
            throw new Error('consumer error')
        })

        const [kafkaHealthy, error] = await kafkaHealthcheck(hub!.kafkaProducer, consumer, statsd, 5000)
        expect(kafkaHealthy).toEqual(false)
        expect(error!.message).toEqual('consumer error')
        expect(statsd.timing).not.toHaveBeenCalled()
    })

    test('healthcheck fails if consumer cannot consume a message within the timeout', async () => {
        const fakeConsumer: any = {
            ...consumer,
            resume: jest.fn(),
            pause: jest.fn(),
            on: jest.fn(),
        }

        const [kafkaHealthy, error] = await kafkaHealthcheck(hub!.kafkaProducer, fakeConsumer, statsd, 0)
        expect(kafkaHealthy).toEqual(false)
        expect(error!.message).toEqual('Consumer did not start fetching messages in time.')
        expect(statsd.timing).not.toHaveBeenCalled()
    })
})
