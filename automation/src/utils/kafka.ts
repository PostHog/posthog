import { config } from '../config'
import { CompressionCodecs, CompressionTypes, Kafka } from 'kafkajs'

const SnappyCodec = require('kafkajs-snappy')

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

export const kafka = new Kafka({
    clientId: 'ingester',
    brokers: ['localhost:9092'],
})

const producerConfig = {
    // Question: Should we disable this setting? We'd need to ensure the retry queues are created somewhere else
    allowAutoTopicCreation: true,
}

export const consumer = kafka.consumer(config.consumerConfig)
export const producer = kafka.producer(producerConfig)
