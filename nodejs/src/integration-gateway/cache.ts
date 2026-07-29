import { DecryptedIntegration } from './types'

/**
 * In-process cache of decrypted integrations, keyed by integration id (not team-scoped — the
 * team filter is applied post-lookup by the service, and `team_id` travels with the cached value,
 * so a wrong-team caller is always filtered out regardless of who populated the entry).
 *
 * A short TTL is the entire staleness story (no push invalidation): safe because Django refreshes
 * OAuth tokens well before expiry, so a <=TTL-stale token is still valid. Plaintext credentials
 * live only in this process's heap and are never written to a shared cache.
 */
export class CredentialCache {
    private store = new Map<number, { value: DecryptedIntegration; expiresAt: number }>()

    constructor(
        private ttlSeconds: number,
        private maxCapacity: number
    ) {}

    get(id: number): DecryptedIntegration | undefined {
        const entry = this.store.get(id)
        if (!entry) {
            return undefined
        }
        if (Date.now() > entry.expiresAt) {
            this.store.delete(id)
            return undefined
        }
        return entry.value
    }

    insert(id: number, value: DecryptedIntegration): void {
        // Evict the oldest inserted entry when at capacity (Map preserves insertion order).
        if (this.store.size >= this.maxCapacity && !this.store.has(id)) {
            const oldest = this.store.keys().next().value
            if (oldest !== undefined) {
                this.store.delete(oldest)
            }
        }
        this.store.set(id, { value, expiresAt: Date.now() + this.ttlSeconds * 1000 })
    }

    clear(): void {
        this.store.clear()
    }
}
