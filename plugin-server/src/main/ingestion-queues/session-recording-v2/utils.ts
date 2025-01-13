import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { KafkaConsumer, PartitionMetadata } from 'node-rdkafka'

import { status } from '../../../utils/status'
import { KafkaMetrics } from './kafka/metrics'
import { KafkaParser } from './kafka/parser'
import { MessageWithTeam } from './teams/types'
import { PersistedRecordingMessage } from './types'

// Helper to return now as a milliseconds timestamp
export const now = () => DateTime.now().toMillis()

export const minDefined = (...args: (number | undefined)[]): number | undefined => {
    const definedArgs = args.filter((arg) => arg !== undefined) as number[]
    return definedArgs.length ? Math.min(...definedArgs) : undefined
}

export const maxDefined = (...args: (number | undefined)[]): number | undefined => {
    const definedArgs = args.filter((arg) => arg !== undefined) as number[]
    return definedArgs.length ? Math.max(...definedArgs) : undefined
}

export const queryWatermarkOffsets = (
    kafkaConsumer: KafkaConsumer | undefined,
    topic: string,
    partition: number,
    timeout = 10000
): Promise<[number, number]> => {
    return new Promise<[number, number]>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }

        kafkaConsumer.queryWatermarkOffsets(topic, partition, timeout, (err, offsets) => {
            if (err) {
                captureException(err)
                status.error('🔥', 'Failed to query kafka watermark offsets', err)
                return reject(err)
            }

            resolve([partition, offsets.highOffset])
        })
    })
}

export const getPartitionsForTopic = (
    kafkaConsumer: KafkaConsumer | undefined,
    topic: string
): Promise<PartitionMetadata[]> => {
    return new Promise<PartitionMetadata[]>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }
        kafkaConsumer.getMetadata({ topic }, (err, meta) => {
            if (err) {
                captureException(err)
                status.error('🔥', 'Failed to get partition metadata', err)
                return reject(err)
            }

            return resolve(meta.topics.find((x) => x.name === topic)?.partitions ?? [])
        })
    })
}

export const getLagMultiplier = (lag: number, threshold = 1000000) => {
    if (lag < threshold) {
        return 1
    }

    return Math.max(0.1, 1 - (lag - threshold) / (threshold * 10))
}

export const convertForPersistence = (
    messages: MessageWithTeam['message']['eventsByWindowId']
): PersistedRecordingMessage[] => {
    return Object.entries(messages).map(([window_id, events]) => {
        return {
            window_id,
            data: events,
        }
    })
}

// Export the parser with metrics instance
export const kafkaParser = new KafkaParser(KafkaMetrics.getInstance())
