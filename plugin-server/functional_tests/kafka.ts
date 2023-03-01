import { HighLevelProducer } from 'node-rdkafka'

import { defaultConfig } from '../src/config/config'

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

export async function produce(topic: string, message: Buffer | null, key: string) {
    producer = producer ?? (await createKafkaProducer())
    await new Promise((resolve, reject) =>
        producer.produce(topic, undefined, message, Buffer.from(key), Date.now(), (err, offset) => {
            if (err) {
                reject(err)
            } else {
                resolve(offset)
            }
        })
    )
    await new Promise((resolve, reject) =>
        producer.flush(10000, (err) => {
            if (err) {
                reject(err)
            } else {
                resolve(null)
            }
        })
    )
}
