import { Writable } from 'stream'

import { status } from '../../../../utils/status'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchMetrics } from './metrics'
import { SessionRecorder } from './recorder'
import { SessionBatchWriter } from './session-batch-writer'

export interface StreamWithFinish {
    stream: Writable
    finish: () => Promise<void>
}

export class SessionBatchRecorder {
    private readonly partitionSessions = new Map<number, Map<string, SessionRecorder>>()
    private readonly partitionSizes = new Map<number, number>()
    private _size: number = 0

    constructor(private readonly offsetManager: KafkaOffsetManager, private readonly writer: SessionBatchWriter) {
        status.debug('🔁', 'session_batch_recorder_created')
    }

    public record(message: MessageWithTeam): number {
        const { partition } = message.message.metadata
        const sessionId = message.message.session_id

        if (!this.partitionSessions.has(partition)) {
            this.partitionSessions.set(partition, new Map())
            this.partitionSizes.set(partition, 0)
        }

        const sessions = this.partitionSessions.get(partition)!
        if (!sessions.has(sessionId)) {
            sessions.set(sessionId, new SessionRecorder())
        }

        const recorder = sessions.get(sessionId)!
        const bytesWritten = recorder.recordMessage(message.message)

        // Update both partition size and total size
        const currentPartitionSize = this.partitionSizes.get(partition)!
        this.partitionSizes.set(partition, currentPartitionSize + bytesWritten)
        this._size += bytesWritten

        this.offsetManager.trackOffset({
            partition: message.message.metadata.partition,
            offset: message.message.metadata.offset,
        })

        status.debug('🔁', 'session_batch_recorder_recorded_message', {
            partition,
            sessionId,
            bytesWritten,
            totalSize: this._size,
        })

        return bytesWritten
    }

    public discardPartition(partition: number): void {
        const partitionSize = this.partitionSizes.get(partition)
        if (partitionSize) {
            status.info('🔁', 'session_batch_recorder_discarding_partition', {
                partition,
                partitionSize,
            })
            this._size -= partitionSize
            this.partitionSizes.delete(partition)
            this.partitionSessions.delete(partition)
            this.offsetManager.discardPartition(partition)
        }
    }

    public async flush(): Promise<void> {
        status.info('🔁', 'session_batch_recorder_flushing', {
            totalSessions: this.partitionSessions.size,
            totalSize: this._size,
        })

        const { stream: outputStream, finish } = await this.writer.open()

        let totalEvents = 0
        let totalSessions = 0
        let totalBytes = 0

        try {
            for (const sessions of this.partitionSessions.values()) {
                for (const recorder of sessions.values()) {
                    const { stream, eventCount } = recorder.end()

                    const trackBytesWritten = new Promise<number>((resolve, reject) => {
                        let bytesWritten = 0
                        stream.on('data', (chunk) => {
                            bytesWritten += chunk.length
                        })
                        stream.on('end', () => resolve(bytesWritten))
                        stream.on('error', reject)
                    })

                    stream.pipe(outputStream, { end: false })
                    const bytesWritten = await trackBytesWritten

                    totalEvents += eventCount
                    totalBytes += bytesWritten
                }
                totalSessions += sessions.size
            }

            outputStream.end()
            await finish()
            await this.offsetManager.commit()

            // Update metrics
            SessionBatchMetrics.incrementBatchesFlushed()
            SessionBatchMetrics.incrementSessionsFlushed(totalSessions)
            SessionBatchMetrics.incrementEventsFlushed(totalEvents)
            SessionBatchMetrics.incrementBytesWritten(totalBytes)

            // Clear sessions, partition sizes, and total size after successful flush
            this.partitionSessions.clear()
            this.partitionSizes.clear()
            this._size = 0

            status.info('🔁', 'session_batch_recorder_flushed', {
                totalEvents,
                totalSessions,
                totalBytes,
            })
        } catch (error) {
            // Log error and cleanup
            status.error('🔁', 'session_batch_recorder_flush_error', {
                error,
                totalEvents,
                totalSessions,
                totalBytes,
            })
            outputStream.destroy()
            throw error
        }
    }

    public get size(): number {
        return this._size
    }
}
