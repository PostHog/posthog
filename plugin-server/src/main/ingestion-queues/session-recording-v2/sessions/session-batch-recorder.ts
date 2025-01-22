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
    readonly size: number
}

export class BaseSessionBatchRecorder implements SessionBatchRecorder {
    private readonly sessions: Map<string, SessionRecorder> = new Map()
    private _size: number = 0

    constructor(private readonly flusher: SessionBatchFlusher) {}

    public record(message: MessageWithTeam): number {
        const sessionId = message.message.session_id

        if (!this.sessions.has(sessionId)) {
            this.sessions.set(sessionId, new SessionRecorder())
        }

        const recorder = this.sessions.get(sessionId)!
        const bytesWritten = recorder.recordMessage(message.message)
        this._size += bytesWritten
        return bytesWritten
    }

    public async flush(): Promise<void> {
        const { stream, finish } = await this.flusher.open()
        for (const recorder of this.sessions.values()) {
            await recorder.dump(stream)
        }
        stream.end()
        await finish()

        // Clear sessions and size after successful flush
        this.sessions.clear()
        this._size = 0
    }

    public get size(): number {
        return this._size
    }
}
