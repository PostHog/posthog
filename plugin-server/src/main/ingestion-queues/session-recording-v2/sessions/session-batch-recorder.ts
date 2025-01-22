import { Writable } from 'stream'

import { MessageWithTeam } from '../teams/types'
import { SessionRecorder } from './recorder'

export interface StreamWithFinish {
    stream: Writable
    finish: () => Promise<void>
}

export interface SessionBatchFlusher {
    open(): Promise<StreamWithFinish>
}

export interface SessionBatchRecorder {
    record(message: MessageWithTeam): number
    flush(): Promise<void>
    discardPartition(partition: number): void
    readonly size: number
}

export class BaseSessionBatchRecorder implements SessionBatchRecorder {
    private readonly partitionSessions = new Map<number, Map<string, SessionRecorder>>()
    private readonly partitionSizes = new Map<number, number>()
    private _size: number = 0

    constructor(private readonly flusher: SessionBatchFlusher) {}

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
        const { stream, finish } = await this.flusher.open()

        // Flush sessions grouped by partition
        for (const sessions of this.partitionSessions.values()) {
            for (const recorder of sessions.values()) {
                await recorder.dump(stream)
            }
        }

        stream.end()
        await finish()

        // Clear sessions, partition sizes, and total size after successful flush
        this.partitionSessions.clear()
        this.partitionSizes.clear()
        this._size = 0
    }

    public get size(): number {
        return this._size
    }
}
