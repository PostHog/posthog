/**
 * NOTE: This file should only be imported for code that wants to fully mock the kafka producer
 *
 * If you just want to observe a real producer class then use `producer.spy.ts`
 */
import { KafkaProducerObserver } from './producer.spy'

import { HighLevelProducer } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../../src/kafka/producer'

const ActualKafkaProducerWrapper = jest.requireActual('../../../src/kafka/producer').KafkaProducerWrapper

jest.mock('../../../src/kafka/producer', () => {
    const mockHighLevelProducer: jest.Mocked<HighLevelProducer> = {
        produce: jest.fn((...args) => args[args.length - 1]?.()),
        flush: jest.fn((...args) => args[args.length - 1]?.()),
        disconnect: jest.fn((...args) => args[args.length - 1]?.()),
        connect: jest.fn((...args) => args[args.length - 1]?.()),
        on: jest.fn(),
        removeAllListeners: jest.fn(),
        getMetadata: jest.fn((opts: any, cb: any) =>
            cb(null, {
                topics: opts?.topic
                    ? [{ name: opts.topic, partitions: [{ id: 0, leader: 0, replicas: [0], isrs: [0] }] }]
                    : [],
                brokers: [{ id: 0, host: 'mock', port: 9092 }],
                orig_broker_id: 0,
                orig_broker_name: 'mock',
            })
        ),
    } as any

    // Rather than calling create we just create a new instance with the underlying node-rdkafka producer mocked.
    const kafkaProducer = new ActualKafkaProducerWrapper(mockHighLevelProducer)

    class MockKafkaProducer {
        static create = jest.fn(() => Promise.resolve(kafkaProducer))
    }

    return {
        KafkaProducerWrapper: MockKafkaProducer,
        _producer: kafkaProducer,
    }
})

export const mockProducer = require('../../../src/kafka/producer')._producer as KafkaProducerWrapper
export const MockKafkaProducerWrapper = require('../../../src/kafka/producer')
    .KafkaProducerWrapper as typeof KafkaProducerWrapper
export const mockProducerObserver = new KafkaProducerObserver(mockProducer)
