import { Kafka, Partitioners } from 'kafkajs'
// NOTE: as we do not import the KafkaProducerWrapper, we do not have the snappy
// compression configured.
// TODO: move configuration of snappy compression to e.g. the app configuration
import { CompressionCodecs, CompressionTypes, logLevel } from 'kafkajs'
import SnappyCodec from 'kafkajs-snappy'

import { defaultConfig } from './src/config/config'
import { KAFKA_APP_METRICS } from './src/config/kafka-topics'
import { startClickHouseConsumer } from './src/main/ingestion-queues/clickhouse-consumer'
CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

export default async function () {
    // The unit tests expect that events and other objects are persisted to
    // ClickHouse, on which we make assertions. This starts the ClickHouse Kafka
    // consumer which will push events etc. into ClickHouse.

    const kafka = (globalThis.kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING }))
    const producer = (globalThis.producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner }))
    await producer.connect()

    globalThis.clickHouseConsumer = await startClickHouseConsumer({
        kafka: kafka,
        producer: producer,
        // TODO: add other topics here as we move await from KafkaTable
        topic: KAFKA_APP_METRICS,
        serverConfig: { ...defaultConfig },
    })
}
