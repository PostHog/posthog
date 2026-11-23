/**
 * Runs a bench workload through the Node consumer on a real Kafka topic, as the counterpart of
 * `logs-ingestion-kafka-bench` in rust/logs-ingestion. Dependencies are in memory and outputs are
 * discarded, as in `logs-consumer-bench.ts`.
 *
 *   tsx src/logs/benchmarks/logs-kafka-bench.ts <workload.json> <topic> <group> <expected> <result.json>
 *
 * The broker comes from KAFKA_CONSUMER_METADATA_BROKER_LIST.
 */
import { readFileSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { Message } from 'node-rdkafka'

import { parseJSON } from '~/common/utils/json-parse'

import { FRAMEWORK_CLASSES, PARITY_REDIS_URL, buildParityConsumer } from '../parity/parity-harness'
import type { ParityScenario } from '../parity/parity-types'

type BatchHandler = (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>
type KafkaBackedConsumer = {
    processKafkaBatch: BatchHandler
    kafkaConsumer: { connect: (handler: BatchHandler) => Promise<void>; disconnect: () => Promise<void> }
}

async function main(): Promise<void> {
    const [workloadPath, topic, group, expectedArg, resultPath] = process.argv.slice(2)
    const expected = Number(expectedArg)
    const scenario = parseJSON(readFileSync(workloadPath, 'utf8')) as ParityScenario
    Object.assign(scenario.config, {
        LOGS_INGESTION_CONSUMER_GROUP_ID: group,
        LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: topic,
    })

    const redis = new Redis(PARITY_REDIS_URL)
    await redis.flushdb()
    await redis.quit()

    const { consumer: built } = buildParityConsumer(scenario, { classes: FRAMEWORK_CLASSES, discard: true })
    const consumer = built as unknown as KafkaBackedConsumer

    let firstMs = 0
    let done = 0
    let batches = 0
    let finish: () => void = () => {}
    const finished = new Promise<void>((resolve) => (finish = resolve))

    await consumer.kafkaConsumer.connect(async (messages) => {
        firstMs ||= Date.now()
        const { backgroundTask } = await consumer.processKafkaBatch(messages)
        return {
            backgroundTask: (async () => {
                await backgroundTask
                batches += 1
                done += messages.length
                // A replayed batch can pass the expected count, so only the crossing writes the result.
                if (done >= expected && done - messages.length < expected) {
                    writeFileSync(
                        resultPath,
                        JSON.stringify({ first_ms: firstMs, last_ms: Date.now(), messages: done, batches }) + '\n'
                    )
                    finish()
                }
            })(),
        }
    })
    await finished
    await consumer.kafkaConsumer.disconnect()
}

void main().then(
    () => process.exit(0),
    (error) => {
        console.error(error)
        process.exit(1)
    }
)
