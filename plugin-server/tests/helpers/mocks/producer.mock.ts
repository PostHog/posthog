/**
 * NOTE: This file should only be imported for code that wants to fully mock the kafka producer
 *
 * If you just want to observe a real producer class then use `producer.spy.ts`
 */

import { KafkaProducerWrapper } from '../../../src/kafka/producer'
import { KafkaProducerObserver } from './producer.spy'

jest.mock('../../../src/kafka/producer', () => {
    const mockKafkaProducer: jest.Mocked<KafkaProducerWrapper> = {
        producer: {
            connect: jest.fn(),
        } as any,
        disconnect: jest.fn(),
        produce: jest.fn().mockReturnValue(Promise.resolve()),
        queueMessages: jest.fn().mockReturnValue(Promise.resolve()),
        flush: jest.fn().mockReturnValue(Promise.resolve()),
    }

    const MockKafkaProducer = {
        create: jest.fn(() => Promise.resolve(mockKafkaProducer)),
    }
    return {
        KafkaProducerWrapper: MockKafkaProducer,
        _producer: mockKafkaProducer,
    }
})

export const mockProducer = require('../../../src/kafka/producer')._producer as KafkaProducerWrapper
export const mockProducerObserver = new KafkaProducerObserver(mockProducer)
