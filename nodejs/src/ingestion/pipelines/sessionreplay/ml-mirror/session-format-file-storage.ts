import {
    SessionBatchFileStorage,
    SessionBatchFileWriter,
    WriteSessionData,
    WriteSessionResult,
} from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-file-storage'

import { usesRawSessionIdentifiers } from './session-identifier-format'

class SessionFormatFileWriter implements SessionBatchFileWriter {
    private readonly writers = new Map<boolean, SessionBatchFileWriter>()

    constructor(
        private readonly legacyStorage: SessionBatchFileStorage,
        private readonly rawStorage: SessionBatchFileStorage
    ) {}

    public writeSession(data: WriteSessionData): Promise<WriteSessionResult> {
        const rawIdentifiers = usesRawSessionIdentifiers(data.sessionId)
        let writer = this.writers.get(rawIdentifiers)
        if (!writer) {
            writer = (rawIdentifiers ? this.rawStorage : this.legacyStorage).newBatch()
            this.writers.set(rawIdentifiers, writer)
        }
        return writer.writeSession(data)
    }

    public async finish(): Promise<void> {
        const results = await Promise.allSettled([...this.writers.values()].map((writer) => writer.finish()))
        for (const result of results) {
            if (result.status === 'rejected') {
                throw result.reason
            }
        }
    }
}

export class SessionFormatFileStorage implements SessionBatchFileStorage {
    constructor(
        private readonly legacyStorage: SessionBatchFileStorage,
        private readonly rawStorage: SessionBatchFileStorage
    ) {}

    public newBatch(): SessionBatchFileWriter {
        return new SessionFormatFileWriter(this.legacyStorage, this.rawStorage)
    }

    public async checkHealth(): Promise<boolean> {
        const health = await Promise.all([this.legacyStorage.checkHealth(), this.rawStorage.checkHealth()])
        return health.every(Boolean)
    }
}
