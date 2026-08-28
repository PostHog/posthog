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
 * vocabulary; 'skipped_race' and the 'failed_*' verdicts come only
 * from the Postgres merge's retrying transaction, and 'error' only
 * from the saga.
 */
export type MergePersonsOutcome =
    | 'merged'
    | 'noop_same_person'
    | 'attached'
    | 'skipped_illegal'
    | 'skipped_already_identified'
    | 'skipped_conflict'
    | 'skipped_move_limit'
    | 'skipped_race'
    | 'failed_source_not_found'
    | 'failed_target_not_found'
    | 'failed_source_has_distinct_ids'
    | 'error'

export interface MergePersonsSourceResult {
    sourceDistinctId: string
    outcome: MergePersonsOutcome
    /** The source person the verdict speaks about, when the backend resolved one. */
    sourcePersonUuid?: string
    /**
     * The source person this verdict destroyed, present only on a merged
     * source. A merged-away person is permanent — it cannot be revived or
     * reassigned — so a caller may reconcile cached state against it
     * without re-reading, which reaches persons cached under distinct ids
     * the request never named. Any other verdict leaves it absent: omitted
     * by the Postgres backend, which names persons by uuid instead, and
     * null from the personhog repository, whose boundary answers every
     * field.
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
     * The source belonging to the event that initiated this request.
     * When a folded merge finds no target person, the Postgres merge
     * bootstraps this source through the sequential path first; the
     * plan's first event can be dropped before the person step, so the
     * initiator is not always the first source.
     */
    triggerSourceDistinctId?: string
    /** The merge event's property ops; each backend applies them to the survivor its own way. */
    eventOps: EventOps
    /** Retry key: a repeated call with the same op id must not merge twice. */
    opId: string
    /** $merge_dangerously legally merges already-identified sources; $identify does not. */
    allowIdentifiedSources: boolean
    /**
     * The caller's move policy, from the same config the processor's
     * over-limit handling reads. The Postgres merge bounds its
     * distinct-id moves by it; the saga backend uses LIMIT/ASYNC's limit
     * as its move-limit guard and falls back to its own configured
     * guard for SYNC, which the saga cannot run unbounded.
     */
    mergeMode: MergeMode
    /** Merge event created_at, epoch millis; becomes the survivor's when older. */
    createdAtMs: number
}

export type MergeFoldAbortReason = 'limit' | 'conflict' | 'deadlock' | 'error'

export interface MergePersonsResult {
    /** The surviving person; null when the merge settled without one. */
    survivor: InternalPerson | null
    results: MergePersonsSourceResult[]
    /** Post-commit ClickHouse production the caller may chain on; absent when the backend produced before returning. */
    kafkaAck?: Promise<void>
    /**
     * Whether the caller still needs its follow-up property update;
     * false when person creation already applied the event's properties.
     * Absent means true.
     */
    survivorNeedsUpdate?: boolean
    /** Multi-source only: the folded transaction rolled back untouched; the caller falls back to per-event merges. */
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
     * Merge the sources into the target through this backend's own merge
     * machinery — the identity service's saga, or the PostgresPersonMerge
     * the Postgres store runs internally. Settled verdicts come back as
     * per-source outcomes; retryable Postgres conflicts throw for the
     * caller's retry loop.
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
