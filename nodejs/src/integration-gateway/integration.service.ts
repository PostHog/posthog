import { EncryptedFields } from '~/common/utils/encryption-utils'

import { CredentialCache } from './cache'
import { RefreshManager } from './refresh/manager'
import { IntegrationRepository } from './repository'
import { DecryptedIntegration } from './types'

/** Outcome of a batch fetch, so the caller can emit an accurate audit line. */
export interface FetchOutcome {
    resolved: Map<number, DecryptedIntegration>
    cacheHits: number
    dbLoaded: number
}

/**
 * Loads, decrypts, caches, and team-scopes integrations. When a `RefreshManager` owns a row's
 * kind, an expired token is refreshed just-in-time on the DB-load path before it is decrypted and
 * cached (so the cache never holds a stale pre-refresh token).
 */
export class IntegrationService {
    constructor(
        private repository: IntegrationRepository,
        private encryptedFields: EncryptedFields,
        private cache: CredentialCache,
        private refresh: RefreshManager | null
    ) {}

    /**
     * Return the decrypted integrations for `ids` that exist AND belong to `teamId`. Ids that are
     * missing or belong to another team are simply absent from the result — a wrong-team id is
     * indistinguishable from a non-existent one, so existence can't be probed across teams.
     */
    async getForTeam(teamId: number, ids: number[]): Promise<FetchOutcome> {
        const resolved = new Map<number, DecryptedIntegration>()
        const misses: number[] = []
        let cacheHits = 0

        for (const id of ids) {
            const hit = this.cache.get(id)
            if (hit) {
                cacheHits++
                resolved.set(id, hit)
            } else {
                misses.push(id)
            }
        }

        let dbLoaded = 0
        if (misses.length > 0) {
            const rows = await this.repository.fetchByIds(misses)
            dbLoaded = rows.length
            // Team-scope BEFORE any refresh/decrypt/cache. Skipping cross-team rows here (rather
            // than only filtering at the end) ensures a wrong-team caller can never trigger a
            // refresh — an outbound OAuth call plus a DB write — against another team's integration.
            const ownRows = rows.filter((row) => row.team_id === teamId)
            // Process misses concurrently: each row's JIT refresh is an independent outbound OAuth
            // call (Redis-locked per integration), so a batch of stale rows refreshes in parallel
            // rather than serially inflating latency with the number of stale rows.
            const decryptedRows = await Promise.all(
                ownRows.map(async (row) => {
                    // No-op when refresh is disabled, the kind/team isn't owned, the token is still
                    // fresh, or the refresh fails (fail-open) — so a stale token is never cached.
                    if (this.refresh?.owns(row.kind, row.team_id)) {
                        row = await this.refresh.refresh(row)
                    }
                    const decrypted: DecryptedIntegration = {
                        id: row.id,
                        team_id: row.team_id,
                        kind: row.kind,
                        config: row.config,
                        sensitive_config: this.encryptedFields.decryptObject(row.sensitive_config, {
                            ignoreDecryptionErrors: true,
                        }),
                    }
                    return decrypted
                })
            )
            for (const decrypted of decryptedRows) {
                this.cache.insert(decrypted.id, decrypted)
                resolved.set(decrypted.id, decrypted)
            }
        }

        // Team-scope isolation for cache hits: the cache is keyed by integration id only, so a value
        // populated by one team could be served to another — drop anything not owned by the caller.
        for (const [id, value] of resolved) {
            if (value.team_id !== teamId) {
                resolved.delete(id)
            }
        }

        return { resolved, cacheHits, dbLoaded }
    }
}
