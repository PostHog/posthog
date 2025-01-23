import { Writable } from 'stream'

import { MessageWithTeam } from '../teams/types'
import { SessionBatchMetrics } from './metrics'
import { SessionRecorder } from './recorder'

export interface StreamWithFinish {
    stream: Writable
    finish: () => Promise<void>
}

export interface SessionBatchWriter {
    open(): Promise<StreamWithFinish>
}

export interface SessionBatchRecorderInterface {
    record(message: MessageWithTeam): number
    flush(): Promise<void>
    discardPartition(partition: number): void
    readonly size: number
}

export class SessionBatchRecorder implements SessionBatchRecorderInterface {
    private readonly partitionSessions = new Map<number, Map<string, SessionRecorder>>()
    private readonly partitionSizes = new Map<number, number>()
    private _size: number = 0

    constructor(private readonly writer: SessionBatchWriter) {}

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

        return bytesWritten
    }

    public discardPartition(partition: number): void {
        const partitionSize = this.partitionSizes.get(partition)
        if (partitionSize) {
            this._size -= partitionSize
            this.partitionSizes.delete(partition)
            this.partitionSessions.delete(partition)
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
