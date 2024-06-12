import { CompressionCodecs, CompressionTypes } from 'kafkajs'
import SnappyCodec from 'kafkajs-snappy'
import { HighLevelProducer } from 'node-rdkafka'

import { defaultConfig } from '../src/config/config'
import { produce as defaultProduce } from '../src/kafka/producer'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

let producer: HighLevelProducer

beforeAll(async () => {
    producer = await createKafkaProducer()
})

afterAll(async () => {
    await new Promise((resolve, reject) =>
        producer?.disconnect((error, data) => {
            return error ? reject(error) : resolve(data)
        })
    )
})

export async function createKafkaProducer() {
    producer = new HighLevelProducer({
        'metadata.broker.list': defaultConfig.KAFKA_HOSTS,
        'linger.ms': 0,
    })

    await new Promise((resolve, reject) =>
        producer.connect(undefined, (error, data) => {
            return error ? reject(error) : resolve(data)
        })
    )

    return producer
}

export async function produce({
    topic,
    message,
    key,
    waitForAck,
}: {
    topic: string
    message: Buffer | null
    key: string
    waitForAck: boolean
}) {
    producer = producer ?? (await createKafkaProducer())
    await defaultProduce({ producer, topic, value: message, key: Buffer.from(key), waitForAck })
}
