import { Code, ConnectError } from '@connectrpc/connect'

import { InternalPerson, TeamId } from '../../types'
import { logger } from '../../utils/logger'
import {
    InternalPersonWithDistinctId,
    PersonReadRepository,
} from '../../worker/ingestion/persons/repositories/person-repository'
import { PersonHogClient } from './client'
import { timedGrpc } from './metrics'

const RETRYABLE_CODES = new Set([
    Code.Unavailable,
    Code.DeadlineExceeded,
    Code.ResourceExhausted,
    Code.Aborted,
    Code.Internal,
    Code.Unknown,
])

function isRetryable(error: unknown): boolean {
    return error instanceof ConnectError && RETRYABLE_CODES.has(error.code)
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Retry a function with exponential backoff on transient gRPC errors.
 * Non-transient errors are thrown immediately.
 */
async function withRetry<T>(fn: () => Promise<T>, maxRetries: number = 2, initialDelayMs: number = 50): Promise<T> {
    let lastError: unknown
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            return await fn()
        } catch (error) {
            lastError = error
            if (!isRetryable(error) || attempt === maxRetries) {
                throw error
            }
            logger.warn('[PersonHogReadRepository] Retryable gRPC error, retrying', {
                attempt: attempt + 1,
                maxRetries,
                error: String(error),
            })
            await sleep(initialDelayMs * Math.pow(2, attempt))
        }
    }
    throw lastError
}

/**
 * Read-only person repository backed by personhog gRPC. No Postgres
 * dependency — all reads go through personhog with automatic retries
 * on transient errors.
 */
export class PersonHogReadRepository implements PersonReadRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private clientLabel: string = 'unknown'
    ) {}

    async fetchPerson(teamId: number, distinctId: string): Promise<InternalPerson | undefined> {
        const results = await withRetry(() =>
            timedGrpc(this.clientLabel, 'fetchPerson', () =>
                this.grpcClient.persons.fetchPersonsByDistinctIds([{ teamId, distinctId }])
            )
        )
        return results.length > 0 ? results[0] : undefined
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[]
    ): Promise<InternalPersonWithDistinctId[]> {
        return withRetry(() =>
            timedGrpc(this.clientLabel, 'fetchPersonsByDistinctIds', () =>
                this.grpcClient.persons.fetchPersonsByDistinctIds(teamPersons)
            )
        )
    }

    async fetchPersonsByPersonIds(teamPersons: { teamId: TeamId; personId: string }[]): Promise<InternalPerson[]> {
        return withRetry(() =>
            timedGrpc(this.clientLabel, 'fetchPersonsByPersonIds', () =>
                this.grpcClient.persons.fetchPersonsByPersonIds(teamPersons)
            )
        )
    }

    async fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number }
    ): Promise<Record<string, string[]>> {
        return withRetry(() =>
            timedGrpc(this.clientLabel, 'fetchDistinctIdsForPersons', () =>
                this.grpcClient.persons.getDistinctIdsForPersons(teamId, personIntIds, options?.limitPerPerson)
            )
        )
    }
}
