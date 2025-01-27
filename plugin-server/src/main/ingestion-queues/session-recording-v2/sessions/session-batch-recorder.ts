import { Writable } from 'stream'

import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { BlackholeSessionBatchWriter } from './blackhole-session-batch-writer'
import { SessionBatchMetrics } from './metrics'
import { SessionRecorder } from './recorder'

export interface StreamWithFinish {
    stream: Writable
    finish: () => Promise<void>
}

export interface SessionBatchWriter {
    open(): Promise<StreamWithFinish>
}

export class SessionBatchRecorder {
    private readonly partitionSessions = new Map<number, Map<string, SessionRecorder>>()
    private readonly partitionSizes = new Map<number, number>()
    private _size: number = 0
    private readonly writer: BlackholeSessionBatchWriter

    constructor(private readonly offsetManager: KafkaOffsetManager) {
        this.writer = new BlackholeSessionBatchWriter()
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

        return bytesWritten
    }

    public discardPartition(partition: number): void {
        const partitionSize = this.partitionSizes.get(partition)
        if (partitionSize) {
            this._size -= partitionSize
            this.partitionSizes.delete(partition)
            this.partitionSessions.delete(partition)
            this.offsetManager.discardPartition(partition)
        }
    }

    public async flush(): Promise<void> {
        const { stream, finish } = await this.writer.open()

        let totalEvents = 0
        let totalSessions = 0
        let totalBytes = 0

        // Flush sessions grouped by partition
        for (const sessions of this.partitionSessions.values()) {
            for (const recorder of sessions.values()) {
                const { eventCount, bytesWritten } = await recorder.write(stream)
                totalEvents += eventCount
                totalBytes += bytesWritten
            }
            totalSessions += sessions.size
        }

        stream.end()
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
    }

    public get size(): number {
        return this._size
    }
}
