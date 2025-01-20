import { Writable } from 'stream'

import { MessageWithTeam } from '../teams/types'
import { SessionRecorder } from './recorder'

export class SessionBatchRecorder {
    private readonly sessions: Map<string, SessionRecorder> = new Map()
    private totalBytesWritten: number = 0

    public record(message: MessageWithTeam): number {
        const sessionId = message.message.session_id

        if (!this.sessions.has(sessionId)) {
            this.sessions.set(sessionId, new SessionRecorder())
        }

        const recorder = this.sessions.get(sessionId)!
        const bytesWritten = recorder.recordMessage(message.message)
        this.totalBytesWritten += bytesWritten
        return bytesWritten
    }

    public async dump(stream: Writable): Promise<void> {
        for (const recorder of this.sessions.values()) {
            await recorder.dump(stream)
        }
    }
}
