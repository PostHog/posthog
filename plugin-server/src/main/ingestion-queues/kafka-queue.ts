import * as Sentry from '@sentry/node'
import { Consumer, Kafka } from 'kafkajs'

import { Hub, Queue } from '../../types'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'

type ConsumerManagementPayload = {
    topic: string
    partitions?: number[] | undefined
}

export abstract class KafkaQueue implements Queue {
    pluginsServer: Hub
    protected kafka: Kafka
    protected consumer: Consumer
    protected wasConsumerRan: boolean
    protected consumerName: string
    protected topic: string

    constructor(pluginsServer: Hub, consumer: Consumer, topic: string, consumerName = '') {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.consumer = consumer
        this.wasConsumerRan = false
        this.consumerName = consumerName
        this.topic = topic
    }

    protected abstract runConsumer(): Promise<void>

    async start(): Promise<void> {
        const startPromise = new Promise<void>(async (resolve, reject) => {
            this.consumer.on(this.consumer.events.GROUP_JOIN, () => {
                resolve()
            })
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            status.info('⏬', `Connecting Kafka consumer ${this.consumerName} to ${this.pluginsServer.KAFKA_HOSTS}...`)
            this.wasConsumerRan = true

            await this.consumer.subscribe({
                topic: this.topic,
            })

            await this.runConsumer()
        })
        return await startPromise
    }

    async pause(partition?: number): Promise<void> {
        if (this.wasConsumerRan && !this.isPaused(partition)) {
            const pausePayload: ConsumerManagementPayload = { topic: this.topic }
            let partitionInfo = ''
            if (partition) {
                pausePayload.partitions = [partition]
                partitionInfo = `(partition ${partition})`
            }

            status.info('⏳', `Pausing Kafka consumer for topic ${this.topic} ${partitionInfo}...`)
            this.consumer.pause([pausePayload])
            status.info('⏸', `Kafka consumer for topic ${this.topic} ${partitionInfo} paused!`)
        }
        return Promise.resolve()
    }

    resume(partition?: number): void {
        if (this.wasConsumerRan && this.isPaused(partition)) {
            const resumePayload: ConsumerManagementPayload = { topic: this.topic }
            let partitionInfo = ''
            if (partition) {
                resumePayload.partitions = [partition]
                partitionInfo = `(partition ${partition})`
            }
            status.info('⏳', `Resuming Kafka consumer for topic ${this.topic} ${partitionInfo}...`)
            this.consumer.resume([resumePayload])
            status.info('▶️', `Kafka consumer for topic ${this.topic} ${partitionInfo} resumed!`)
        }
    }

    isPaused(partition?: number): boolean {
        // if we pass a partition, check that as well, else just return if the topic is paused
        return this.consumer
            .paused()
            .some(({ topic, partitions }) => topic === this.topic && (!partition || partitions.includes(partition)))
    }

    async stop(): Promise<void> {
        status.info('⏳', 'Stopping Kafka queue...')
        try {
            await this.consumer.stop()
            status.info('⏹', `Kafka consumer ${this.consumerName} stopped!`)
        } catch (error) {
            status.error('⚠️', `An error occurred while stopping Kafka consumer ${this.consumerName}:\n`, error)
        }
        try {
            await this.consumer.disconnect()
        } catch {}
    }

    protected static buildConsumer(kafka: Kafka, consumerName: string, groupId?: string): Consumer {
        const consumer = kafka.consumer({
            groupId: groupId ?? 'clickhouse-ingestion',
            readUncommitted: false,
        })
        const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT } = consumer.events
        consumer.on(GROUP_JOIN, ({ payload: { groupId } }) => {
            status.info('✅', `Kafka consumer ${consumerName} joined group ${groupId}!`)
        })
        consumer.on(CRASH, ({ payload: { error, groupId } }) => {
            status.error('⚠️', `Kafka consumer ${consumerName} group ${groupId} crashed:\n`, error)
            Sentry.captureException(error)
            killGracefully()
        })
        consumer.on(CONNECT, () => {
            status.info('✅', `Kafka consumer ${consumerName} connected!`)
        })
        consumer.on(DISCONNECT, () => {
            status.info('🛑', `Kafka consumer ${consumerName} disconnected!`)
        })
        return consumer
    }
}
