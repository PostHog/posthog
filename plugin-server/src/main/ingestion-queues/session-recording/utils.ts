import { DateTime } from 'luxon'
import path from 'path'

import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer } from '../../../kafka/batch-consumer'
import { status } from '../../../utils/status'
import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: message.events,
    }
}

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
    batchConsumer: BatchConsumer | undefined,
    partition: number
): Promise<[number, number]> => {
    return new Promise<[number, number]>((resolve, reject) => {
        if (!batchConsumer) {
            return reject('Not connected')
        }
        batchConsumer.consumer.queryWatermarkOffsets(
            KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
            partition,
            (err, offsets) => {
                if (err) {
                    status.error('🔥', 'Failed to query kafka watermark offsets', err)
                    return reject()
                }

                resolve([partition, offsets.highOffset])
            }
        )
    })
}
