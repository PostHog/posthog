import { DeleteKeyResult, KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { RecordingApiMetrics } from './metrics'

// Times each call that misses the Redis cache, so the AWS deadline can follow the measured tail.
export class TimedKeyStore implements KeyStore {
    constructor(private readonly delegate: KeyStore) {}

    start(): Promise<void> {
        return this.delegate.start()
    }

    stop(): void {
        this.delegate.stop()
    }

    generateKey(sessionId: string, teamId: number, retentionDays: number): Promise<SessionKey> {
        return this.timed('generate', () => this.delegate.generateKey(sessionId, teamId, retentionDays))
    }

    getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        return this.timed('get', () => this.delegate.getKey(sessionId, teamId))
    }

    deleteKey(sessionId: string, teamId: number, deletedBy: string): Promise<DeleteKeyResult> {
        return this.timed('delete', () => this.delegate.deleteKey(sessionId, teamId, deletedBy))
    }

    private async timed<T>(operation: 'generate' | 'get' | 'delete', call: () => Promise<T>): Promise<T> {
        const start = performance.now()
        let result: 'ok' | 'error' = 'error'
        try {
            const value = await call()
            result = 'ok'
            return value
        } finally {
            RecordingApiMetrics.observeKeyStore(operation, result, (performance.now() - start) / 1000)
        }
    }
}
