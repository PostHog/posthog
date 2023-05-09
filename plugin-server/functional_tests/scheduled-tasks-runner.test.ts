import { Message } from 'node-rdkafka-acosom'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { BatchConsumer, startBatchConsumer } from '../src/kafka/batch-consumer'
import { getMetric } from './api'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

describe('dlq handling', () => {
    // Test out some error cases that we wouldn't be able to handle without
    // producing to the jobs queue directly.

    let dlq: Message[]
    let dlqConsumer: BatchConsumer

    beforeAll(async () => {
        dlq = []
        dlqConsumer = await startBatchConsumer({
            connectionConfig: { 'metadata.broker.list': defaultConfig.KAFKA_HOSTS },
            groupId: 'scheduled-tasks-consumer-test',
            topic: 'scheduled_tasks_dlq',
            autoResetOffsets: 'earliest',
            eachBatch: (messages) => {
                dlq.push(...messages)
                return Promise.resolve()
            },
        })
    })

    afterAll(async () => {
        await dlqConsumer.stop()
    })

    test.concurrent(`handles empty messages`, async () => {
        const key = uuidv4()

        await produce({ topic: 'scheduled_tasks', message: null, key })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    })

    test.concurrent(`handles invalid JSON`, async () => {
        const key = uuidv4()

        await produce({ topic: 'scheduled_tasks', message: Buffer.from('invalid json'), key })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    })

    test.concurrent(`handles invalid taskType`, async () => {
        const key = uuidv4()

        await produce({
            topic: 'scheduled_tasks',
            message: Buffer.from(JSON.stringify({ taskType: 'invalidTaskType', pluginConfigId: 1 })),
            key,
        })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    })

    test.concurrent(`handles invalid pluginConfigId`, async () => {
        const key = uuidv4()

        await produce({
            topic: 'scheduled_tasks',
            message: Buffer.from(JSON.stringify({ taskType: 'runEveryMinute', pluginConfigId: 'asdf' })),
            key,
        })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    })

    test.concurrent('consumer updates timestamp exported to prometheus', async () => {
        // NOTE: it may be another event other than the one we emit here that causes
        // the gauge to increase, but pushing this event through should at least
        // ensure that the gauge is updated.
        const metricBefore = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: { topic: 'scheduled_tasks', partition: '0', groupId: 'scheduled-tasks-runner' },
        })

        // NOTE: we don't actually care too much about the contents of the
        // message, just that it triggeres the consumer to try to process it.
        await produce({ topic: 'scheduled_tasks', message: Buffer.from(''), key: '' })

        await waitForExpect(async () => {
            const metricAfter = await getMetric({
                name: 'latest_processed_timestamp_ms',
                type: 'GAUGE',
                labels: { topic: 'scheduled_tasks', partition: '0', groupId: 'scheduled-tasks-runner' },
            })
            expect(metricAfter).toBeGreaterThan(metricBefore)
            expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
            expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
        }, 10_000)
    })
})
