import {
    SessionBatchFileStorage,
    SessionBatchFileWriter,
    WriteSessionData,
    WriteSessionResult,
} from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-file-storage'

import { sessionStartMonth, usesRawSessionIdentifiers, usesV3Dataset } from './session-identifier-format'

class SessionFormatFileWriter implements SessionBatchFileWriter {
    private readonly writers = new Map<string, SessionBatchFileWriter>()

    constructor(
        private readonly legacyStorage: SessionBatchFileStorage,
        private readonly rawStorage: (month?: string) => SessionBatchFileStorage,
        private readonly v3Storage: (month?: string) => SessionBatchFileStorage
    ) {}

    public writeSession(data: WriteSessionData): Promise<WriteSessionResult> {
        const v3 = usesV3Dataset(data.sessionId)
        const rawIdentifiers = v3 || usesRawSessionIdentifiers(data.sessionId)
        const month = rawIdentifiers ? sessionStartMonth(data.sessionId) : undefined
        const partition = v3 ? `v3/${month}` : (month ?? 'legacy')
        let writer = this.writers.get(partition)
        if (!writer) {
            const storage = v3 ? this.v3Storage(month) : rawIdentifiers ? this.rawStorage(month) : this.legacyStorage
            writer = storage.newBatch()
            this.writers.set(partition, writer)
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
        private readonly rawStorage: (month?: string) => SessionBatchFileStorage,
        private readonly v3Storage: (month?: string) => SessionBatchFileStorage
    ) {}

    public newBatch(): SessionBatchFileWriter {
        return new SessionFormatFileWriter(this.legacyStorage, this.rawStorage, this.v3Storage)
    }

    public async checkHealth(): Promise<boolean> {
        const health = await Promise.all([
            this.legacyStorage.checkHealth(),
            this.rawStorage().checkHealth(),
            this.v3Storage().checkHealth(),
        ])
        return health.every(Boolean)
    }
}
