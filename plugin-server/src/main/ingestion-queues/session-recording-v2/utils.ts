import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { KafkaConsumer, MessageHeader, PartitionMetadata } from 'node-rdkafka'
import path from 'path'

import { status } from '../../../utils/status'
import { KafkaMetrics } from './kafka/kafka-metrics'
import { KafkaParser } from './kafka/kafka-parser'
import { TeamIDWithConfig } from './session-recordings-consumer'
import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

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

export const bufferFileDir = (root: string) => path.join(root, 'session-buffer-files')

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

export async function readTokenFromHeaders(
    headers: MessageHeader[] | undefined,
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
) {
    const tokenHeader = headers?.find((header: MessageHeader) => {
        // each header in the array is an object of key to value
        // because it's possible to have multiple headers with the same key
        // but, we don't support that. the first truthy match we find is the one we use
        return header.token
    })?.token

    const token = typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()

    let teamIdWithConfig: TeamIDWithConfig | null = null

    if (token) {
        teamIdWithConfig = await getTeamFn(token)
    }
    return { token, teamIdWithConfig }
}

export const convertForPersistence = (
    messages: IncomingRecordingMessage['eventsByWindowId']
): PersistedRecordingMessage[] => {
    return Object.entries(messages).map(([window_id, events]) => {
        return {
            window_id,
            data: events,
        }
    })
}

export const allSettledWithConcurrency = async <T, Q>(
    concurrency: number,
    arr: T[],
    fn: (item: T, context: { index: number; break: () => void }) => Promise<Q>
): Promise<{ error?: any; result?: Q }[]> => {
    // This function processes promises in parallel like Promise.allSettled, but with a maximum concurrency

    let breakCalled = false

    return new Promise<{ error?: any; result?: Q }[]>((resolve) => {
        const results: { error?: any; result?: Q }[] = []
        const remaining = [...arr]
        let runningCount = 0

        const run = () => {
            while (remaining.length && runningCount < concurrency) {
                if (breakCalled) {
                    return
                }
                const item = remaining.shift()
                if (item) {
                    const arrIndex = arr.indexOf(item)
                    runningCount += 1
                    fn(item, {
                        index: arrIndex,
                        break: () => {
                            breakCalled = true
                            return resolve(results)
                        },
                    })
                        .then((result) => {
                            results[arrIndex] = { result: result }
                        })
                        .catch((err) => {
                            results[arrIndex] = { error: err }
                        })
                        .finally(() => {
                            runningCount -= 1
                            run()
                        })
                }
            }

            if (remaining.length === 0 && !runningCount) {
                return !breakCalled ? resolve(results) : undefined
            }
        }

        run()
    })
}

// Export the parser with metrics instance
export const kafkaParser = new KafkaParser(KafkaMetrics.getInstance())
