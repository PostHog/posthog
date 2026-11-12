import { DeleteKeyResult, KeyStore, SessionKey } from './types'

// Parallel block fetches for one session share a single KMS and DynamoDB read when the Redis cache misses. Only the
// in-flight promise is shared, never a settled key, so nothing outlives the lookup that produced it.
export class SingleFlightKeyStore implements KeyStore {
    private readonly inFlight = new Map<string, Promise<SessionKey>>()

    constructor(private readonly delegate: KeyStore) {}

    start(): Promise<void> {
        return this.delegate.start()
    }

    stop(): void {
        this.delegate.stop()
    }

    generateKey(sessionId: string, teamId: number, retentionDays: number): Promise<SessionKey> {
        return this.delegate.generateKey(sessionId, teamId, retentionDays)
    }

    getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const id = `${teamId}:${sessionId}`
        const pending = this.inFlight.get(id)
        if (pending) {
            return pending
        }
        const lookup: Promise<SessionKey> = this.delegate.getKey(sessionId, teamId).finally(() => {
            // A delete may have replaced this entry with a newer lookup, which must stay shared.
            if (this.inFlight.get(id) === lookup) {
                this.inFlight.delete(id)
            }
        })
        this.inFlight.set(id, lookup)
        return lookup
    }

    deleteKey(sessionId: string, teamId: number, deletedBy: string): Promise<DeleteKeyResult> {
        // A caller arriving after the delete must not join a lookup that started before it.
        this.inFlight.delete(`${teamId}:${sessionId}`)
        return this.delegate.deleteKey(sessionId, teamId, deletedBy)
    }
}
