import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult } from '~/common/utils/db/db'
import { BatchWritingStore } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '~/types'

import { MergeMode } from './person-merge-types'
import { EventOps } from './person-update'

export type FlushResult = {
    messages: PersonMessage[]
    teamId: number
    distinctId?: string
    uuid?: string
}

/** One source distinct id to merge into the target, with the event that asked for it. */
export interface MergePersonsSource {
    distinctId: string
    eventUuid: string
}

/**
 * Per-source verdicts a merge can answer. Both backends share the
 * vocabulary; 'skipped_race' and the 'failed_*' verdicts come only from the
 * Postgres merge's retrying transaction, and 'error' in practice only from
 * the saga.
 */
export type MergePersonsOutcome =
    | 'merged'
    | 'noop_same_person'
    | 'attached'
    | 'skipped_illegal'
    | 'skipped_already_identified'
    | 'skipped_conflict'
    | 'skipped_move_limit'
    /**
     * The operation was definitively refused before destroying anything
     * and aborted; the recorded verdict replays on every retry, so the
     * pair settles as a lost merge rather than retrying as a conflict.
     */
    | 'skipped_refused'
    | 'skipped_race'
    | 'failed_source_not_found'
    | 'failed_target_not_found'
    | 'failed_source_has_distinct_ids'
    | 'error'
    /**
     * A verdict this build cannot name, which only a backend running ahead
     * of it can produce. Distinct from 'error' because the merge may well
     * have happened; nothing here knows either way.
     */
    | 'unknown'

export interface MergePersonsSourceResult {
    sourceDistinctId: string
    outcome: MergePersonsOutcome
    /** The source person the verdict speaks about. Postgres only; the saga reports ids. */
    sourcePersonUuid?: string
    /**
     * The source person this verdict destroyed, on a merged source only: a
     * merged-away person is permanent, so a caller may reconcile cached
     * state against it without re-reading. On every other verdict the
     * Postgres backend omits it and the personhog client answers null.
     */
    sourcePersonId?: string | null
}

export interface MergePersonsRequest {
    teamId: number
    targetDistinctId: string
    /**
     * Ordered; earlier sources beat later ones on property precedence,
     * the target beats all. More than one source only from a fold plan.
     */
    sources: MergePersonsSource[]
    /**
     * The source belonging to the event that initiated this request; not
     * always the first source, since the plan's first event can be dropped
     * before the person step. The Postgres merge bootstraps it through the
     * sequential path when a folded merge finds no target.
     */
    triggerSourceDistinctId?: string
    /** The merge event's property ops; each backend applies them to the survivor its own way. */
    eventOps: EventOps
    /**
     * The merge-triggering event's uuid, the idempotency root: backends
     * derive their durable op ids from it, so a repeated delivery of the
     * same event must present the same value and cannot merge twice.
     */
    eventUuid: string
    /** $merge_dangerously legally merges already-identified sources; $identify does not. */
    allowIdentifiedSources: boolean
    /**
     * The caller's move policy, from the same config the processor's
     * over-limit handling reads. Postgres bounds its distinct-id moves by it;
     * the saga uses LIMIT/ASYNC's limit as its guard and its own configured
     * one for SYNC, which it cannot run unbounded.
     */
    mergeMode: MergeMode
    /**
     * Merge event created_at, epoch millis; consulted only where nothing
     * resolves and a person is born from the request. Otherwise both
     * backends give the survivor the earliest created_at among itself and
     * the persons merged into it.
     */
    createdAtMs: number
}

export type MergeFoldAbortReason = 'limit' | 'conflict' | 'refused' | 'deadlock' | 'error'

export interface MergePersonsResult {
    /** The surviving person; null when the merge settled without one. */
    survivor: InternalPerson | null
    results: MergePersonsSourceResult[]
    /** Post-commit ClickHouse production the caller may chain on; absent when the backend produced before returning. */
    kafkaAck?: Promise<void>
    /**
     * Whether the caller still needs its follow-up property update; absent
     * means true. Postgres reports false when its own creation applied the
     * event's properties or conflicted onto an already-identified person;
     * personhog only for a newborn that is also identified.
     */
    survivorNeedsUpdate?: boolean
    /**
     * Multi-source only: the folded transaction rolled back and the caller
     * falls back to per-event merges. Not always untouched — a bootstrap
     * creation can commit before the fold begins, and its `kafkaAck` travels
     * on this result for the caller to await.
     */
    foldAborted?: MergeFoldAbortReason
}

/** Which person-storage backend a store writes to. Labels metrics whose causes differ between them. */
export type PersonsBackend = 'postgres' | 'personhog'

export interface PersonsStore extends BatchWritingStore<FlushResult> {
    readonly backend: PersonsBackend

    /** Existence-class read; replica-backed where the backend has one. */
    fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null>

    /** Update-class read from the authoritative side; its answer feeds writes. */
    fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null>

    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<CreatePersonResult>

    /**
     * Applies one event's extracted ops to a person, resolving what they
     * mean against this store's own state: snapshot refinement, the
     * identity OR-merge, the last-seen advance, and whether anything is
     * worth writing at all.
     */
    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]>

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    /**
     * Merge the sources into the target through this backend's own machinery,
     * either the identity service's saga or PostgresPersonMerge. Settled
     * verdicts come back as per-source outcomes; retryable Postgres conflicts
     * throw for the caller's retry loop.
     */
    mergePersons(request: MergePersonsRequest, batchId: number): Promise<MergePersonsResult>

    personPropertiesSize(personId: string, teamId: number): Promise<number>

    /**
     * Stop any background work (e.g., periodic metric emission) and flush
     * remaining accumulated metrics. Called on graceful shutdown. Does NOT
     * clear data caches.
     */
    shutdown(): Promise<void>

    /**
     * Best-effort cache warmer. Entries carry their own batchIds so one
     * fetch can serve concurrent batches' eviction tracking.
     */
    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void>

    flush(): Promise<FlushResult[]>

    /**
     * Releases cache entries associated with the given batch ID, using reference
     * counting so entries shared across concurrent batches are only evicted when
     * all referencing batches have completed.
     */
    releaseBatch(batchId: number): void
}
