import { CompressionCodecs, CompressionTypes } from 'kafkajs'
import SnappyCodec from 'kafkajs-snappy'
import { HighLevelProducer } from 'node-rdkafka-acosom'

import { defaultConfig } from '../src/config/config'
import { flushProducer, produce } from '../src/kafka/producer'

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
    })

    await new Promise((resolve, reject) =>
        producer.connect(undefined, (error, data) => {
            return error ? reject(error) : resolve(data)
        })
    )

    return producer
}

export async function produceAndFlush({ topic, message, key }: { topic: string; message: Buffer | null; key: string }) {
    producer = producer ?? (await createKafkaProducer())
    await produce({ producer, topic, value: message, key: Buffer.from(key) })
    await flushProducer(producer)
}
