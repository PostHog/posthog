import { isEqual } from 'lodash'
import { DateTime } from 'luxon'

import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { PersonDistinctIdsOutput, PersonMergeEventsOutput, PersonsOutput } from '~/common/outputs'
import { FILTERED_PERSON_UPDATE_PROPERTIES } from '~/common/persons/person-property-utils'
import { MergePersonUpdate, PersonUpdate, toInternalPerson } from '~/common/persons/person-update-batch'
import { InternalPersonWithDistinctId, PersonRepository } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { InternalPerson } from '~/types'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { EventOps } from './person-update'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

jest.mock('~/common/persons/metrics', () => ({
    observeLatencyByVersion: jest.fn(),
    personCacheOperationsCounter: { inc: jest.fn() },
    personCacheSizeHistogram: { observe: jest.fn() },
    personDatabaseOperationsPerBatchHistogram: { observe: jest.fn() },
    personFallbackOperationsCounter: { inc: jest.fn() },
    personFetchForCheckingCacheOperationsCounter: { inc: jest.fn() },
    personFetchForUpdateCacheOperationsCounter: { inc: jest.fn() },
    personFlushBatchSizeHistogram: { observe: jest.fn() },
    personFlushLatencyHistogram: { observe: jest.fn() },
    personFlushOperationsCounter: { inc: jest.fn() },
    personMethodCallsPerBatchHistogram: { observe: jest.fn() },
    personOptimisticUpdateConflictsPerBatchCounter: { inc: jest.fn() },
    personProfileBatchIgnoredPropertiesCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personProfileIgnoredPropertiesCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personProfileUpdateOutcomeCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personProfileBatchUpdateOutcomeCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personPropertyKeyUpdateCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personRetryAttemptsHistogram: { observe: jest.fn() },
    personWriteMethodAttemptCounter: { inc: jest.fn() },
    personWriteMethodLatencyHistogram: { observe: jest.fn() },
    totalPersonUpdateLatencyPerBatchHistogram: { observe: jest.fn() },
}))

type Held = { label: string; deliver: () => void }
type RowSnapshot = { version: number; properties: Record<string, unknown> }
type Landing = { value: unknown; seq: number; version: number }

/** Reads on master too, where PersonUpdate has no set-once lane. */
const setOnceOf = (update: { properties_to_set_once?: Record<string, unknown> }): Record<string, unknown> =>
    update.properties_to_set_once ?? {}

/**
 * Rows with the batch statement's per-key semantics. A held call still reads or commits at call
 * time; only its answer waits, so the test decides the order results reach the store.
 */
class FakePersonRepository {
    readonly rows = new Map<string, InternalPerson>()
    readonly distinctToUuid = new Map<string, string>()
    readonly held: Held[] = []
    /** The newest row version the store has received per person, from a write result or a fetch. */
    readonly newestDelivered = new Map<string, RowSnapshot>()
    /** Every value each row has held per key, in commit order, whichever writer committed it. */
    readonly committed = new Map<string, Map<string, { value: unknown; at: number }[]>>()
    /** Commit counter, so a value in the history can be placed before or after a merge. */
    clock = 0
    /** Per person and key this pod wrote, the row value its newest landed write left, in commit order. */
    readonly podLanded = new Map<string, Map<string, Landing>>()
    /** Writes that sent a value this pod had landed on that row before, over another value the row held by then. */
    readonly replayed: string[] = []
    /** Every value this pod's writes have landed per row and key, so a second landing of one is a replay. */
    readonly podLandedValues = new Map<string, Map<string, unknown[]>>()
    /** Another pod's last write per row and key, which this pod must leave alone unless it wrote that key. */
    readonly otherPodLast = new Map<string, Map<string, unknown>>()
    /** Keys this pod's writes have ever carried per row. */
    readonly podCarried = new Map<string, Set<string>>()
    /** Every write call as it came in, for reading one seed by hand. */
    readonly writes: string[] = []
    /** The driver's current step, stamped on the write log. */
    step = -1
    /** Writes that carried nothing and changed no scalar: the store should not have sent them. */
    readonly idleWrites: string[] = []
    private seq = 0
    holdWrites = false
    holdFetches = false
    /** How many of the next row reads fail as a transient repository error. */
    fetchFailures = 0
    private nextId = 1

    addPerson(uuid: string, distinctIds: string[], properties: Record<string, unknown>, teamId = 1): InternalPerson {
        const row: InternalPerson = {
            id: String(this.nextId++),
            uuid,
            team_id: teamId,
            properties: { ...properties },
            properties_last_updated_at: {},
            properties_last_operation: {},
            created_at: DateTime.fromISO('2026-01-01T00:00:00Z', { zone: 'utc' }),
            version: 1,
            is_identified: false,
            is_user_id: null,
            last_seen_at: null,
        }
        this.rows.set(uuid, row)
        this.recordCommit(row)
        for (const distinctId of distinctIds) {
            this.distinctToUuid.set(`${teamId}:${distinctId}`, uuid)
        }
        return this.snapshot(row)
    }

    /** Another pod merged source into target: carried keys fill gaps, the ids move, the source row goes. */
    mergeAway(sourceUuid: string, targetUuid: string): void {
        const source = this.rows.get(sourceUuid)!
        const target = this.rows.get(targetUuid)!
        for (const [key, value] of Object.entries(source.properties)) {
            if (!Object.hasOwn(target.properties, key)) {
                this.noteOtherPod(targetUuid, key, value)
            }
        }
        target.properties = { ...source.properties, ...target.properties }
        target.version += 1
        this.recordCommit(target)
        for (const [key, uuid] of this.distinctToUuid) {
            if (uuid === sourceUuid) {
                this.distinctToUuid.set(key, targetUuid)
            }
        }
        this.rows.delete(sourceUuid)
    }

    /** Another pod's per-key write. */
    otherPodSet(uuid: string, properties: Record<string, unknown>): void {
        const row = this.rows.get(uuid)!
        row.properties = { ...row.properties, ...properties }
        row.version += 1
        this.recordCommit(row)
        Object.entries(properties).forEach(([key, value]) => this.noteOtherPod(uuid, key, value))
    }

    /** Another pod's per-key unset. */
    otherPodUnset(uuid: string, key: string): void {
        const row = this.rows.get(uuid)!
        delete row.properties[key]
        row.version += 1
        this.recordCommit(row)
        this.recordAbsent(uuid, key)
        this.noteOtherPod(uuid, key, undefined)
    }

    /** The merge transaction's id move, called on this fake as the transaction. */
    moveDistinctIds = jest.fn((source: InternalPerson, target: InternalPerson) => {
        const moved: string[] = []
        for (const [key, uuid] of this.distinctToUuid) {
            if (uuid === source.uuid) {
                this.distinctToUuid.set(key, target.uuid)
                moved.push(key.slice(key.indexOf(':') + 1))
            }
        }
        return Promise.resolve({ success: true, messages: [], distinctIdsMoved: moved })
    })

    release(index = 0): void {
        const [held] = this.held.splice(index, 1)
        held.deliver()
    }

    releaseAll(): void {
        while (this.held.length > 0) {
            this.release(0)
        }
    }

    labels(): string[] {
        return this.held.map((held) => held.label)
    }

    async settle(predicate: () => boolean): Promise<void> {
        for (let i = 0; i < 200 && !predicate(); i++) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        if (!predicate()) {
            throw new Error(`condition never held; held: ${this.labels().join(', ')}`)
        }
    }

    private failing(label: string): Promise<never> | undefined {
        if (this.fetchFailures === 0) {
            return undefined
        }
        this.fetchFailures--
        return this.fail(
            this.holdFetches,
            label,
            Object.assign(new Error('persons unavailable'), { isRetriable: true })
        )
    }

    fetchPerson = jest.fn((teamId: number, distinctId: string) => {
        const failure = this.failing(`fetch:${distinctId}`)
        if (failure) {
            return failure
        }
        const person = this.lookup(teamId, distinctId)
        this.noteRead(`fetch:${distinctId}`, [person])
        return this.deliver(this.holdFetches, `fetch:${distinctId}`, person, () => this.observePerson(person))
    })

    fetchPersonsByDistinctIds = jest.fn((keys: { teamId: number; distinctId: string }[]) => {
        const failure = this.failing(`prefetch:${keys.map((key) => key.distinctId).join(',')}`)
        if (failure) {
            return failure
        }
        const persons = keys.flatMap(({ teamId, distinctId }): InternalPersonWithDistinctId[] => {
            const person = this.lookup(teamId, distinctId)
            return person ? [{ ...person, distinct_id: distinctId }] : []
        })
        this.noteRead(`prefetch:${keys.map((key) => key.distinctId).join(',')}`, persons)
        return this.deliver(this.holdFetches, `prefetch:${keys.map((key) => key.distinctId).join(',')}`, persons, () =>
            persons.forEach((person) => this.observePerson(person))
        )
    })

    fetchPersonsForUpdateByDistinctIds = jest.fn((teamId: number, distinctIds: string[]) => {
        const failure = this.failing(`fetchForUpdate:${distinctIds.join(',')}`)
        if (failure) {
            return failure
        }
        const persons = distinctIds.flatMap((distinctId): InternalPersonWithDistinctId[] => {
            const person = this.lookup(teamId, distinctId)
            return person ? [{ ...person, distinct_id: distinctId }] : []
        })
        this.noteRead(`fetchForUpdate:${distinctIds.join(',')}`, persons)
        return this.deliver(this.holdFetches, `fetchForUpdate:${distinctIds.join(',')}`, persons, () =>
            persons.forEach((person) => this.observePerson(person))
        )
    })

    updatePersonsBatch = jest.fn((updates: PersonUpdate[]) => {
        const results = new Map<
            string,
            {
                success: boolean
                version?: number
                kafkaMessage?: object
                properties?: Record<string, unknown>
                person?: InternalPerson
                error?: Error
            }
        >()
        for (const update of updates) {
            this.writes.push(
                `write@${this.step} ${update.uuid} (entry ${update.id}) set=${JSON.stringify(update.properties_to_set)} setOnce=${JSON.stringify(setOnceOf(update))} unset=${JSON.stringify(update.properties_to_unset)} identified=${update.is_identified}/${update.original_is_identified} -> ${this.rows.has(update.uuid) ? 'lands' : 'no row'}`
            )
            // UNNEST applies one source row per target row, so a repeated uuid changes nothing more.
            if (results.has(update.uuid)) {
                continue
            }
            const row = this.rows.get(update.uuid)
            if (!row || row.team_id !== update.team_id) {
                results.set(update.uuid, { success: false, error: new NoRowsUpdatedError(`no row ${update.uuid}`) })
                continue
            }
            // Master's statement replaces the whole property map and every scalar; the branch's merges per key.
            const snapshot = SNAPSHOT_SQL || !Object.hasOwn(update, 'properties_to_set_once')
            const carried = snapshot
                ? { ...update.properties, ...update.properties_to_set }
                : { ...setOnceOf(update), ...update.properties_to_set }
            this.noteReplays(row, snapshot ? carried : this.filling(row, update))
            const properties = snapshot
                ? { ...carried }
                : { ...carried, ...row.properties, ...update.properties_to_set }
            for (const key of update.properties_to_unset) {
                delete properties[key]
            }
            if (!snapshot && Object.keys(carried).length === 0 && update.properties_to_unset.length === 0) {
                const identifies = update.is_identified && !row.is_identified
                const backdates = update.created_at < row.created_at
                const advances = !!update.last_seen_at && (!row.last_seen_at || update.last_seen_at > row.last_seen_at)
                if (!identifies && !backdates && !advances) {
                    this.idleWrites.push(`${update.uuid} v${row.version}`)
                }
            }
            row.properties = properties
            if (snapshot) {
                row.is_identified = update.is_identified
                row.created_at = update.created_at
                row.last_seen_at = update.last_seen_at
            } else {
                row.is_identified = row.is_identified || update.is_identified
                row.created_at = DateTime.min(row.created_at, update.created_at)
                if (update.last_seen_at && (!row.last_seen_at || update.last_seen_at > row.last_seen_at)) {
                    row.last_seen_at = update.last_seen_at
                }
            }
            row.version += 1
            this.recordCommit(row)
            update.properties_to_unset.forEach((key) => this.recordAbsent(update.uuid, key))
            this.noteLanded(row, [...Object.keys(carried), ...update.properties_to_unset])
            results.set(update.uuid, {
                success: true,
                version: row.version,
                kafkaMessage: {},
                properties: { ...row.properties },
                person: this.snapshot(row),
            })
        }
        return this.deliver(this.holdWrites, `write:${updates.map((update) => update.uuid).join(',')}`, results, () => {
            for (const [uuid, result] of results) {
                if (result.success) {
                    this.observe(uuid, { version: result.version!, properties: result.properties! })
                }
            }
        })
    })

    /** Master's single-row write: the whole snapshot replaces the row. */
    updatePerson = jest.fn((person: InternalPerson, update: Partial<InternalPerson>) => {
        const row = this.rows.get(person.uuid)
        if (!row || row.team_id !== person.team_id) {
            return this.fail(
                this.holdWrites,
                `updatePerson:${person.uuid}`,
                new NoRowsUpdatedError(`no row ${person.uuid}`)
            )
        }
        this.noteReplays(row, update.properties ?? {})
        row.properties = { ...(update.properties ?? row.properties) }
        row.is_identified = update.is_identified ?? row.is_identified
        row.created_at = update.created_at ?? row.created_at
        row.last_seen_at = update.last_seen_at ?? row.last_seen_at
        row.version += 1
        this.recordCommit(row)
        this.noteLanded(row, Object.keys(row.properties))
        const written = this.snapshot(row)
        return this.deliver(this.holdWrites, `updatePerson:${person.uuid}`, [written, [], false] as const, () =>
            this.observePerson(written)
        )
    })

    /** The version-checked write: the record's whole view replaces the row when the version still matches. */
    updatePersonAssertVersion = jest.fn((update: PersonUpdate) => {
        const row = this.rows.get(update.uuid)
        this.writes.push(
            `cas ${update.uuid} (entry ${update.id}) v${update.version} vs row v${row?.version ?? '-'} set=${JSON.stringify(update.properties_to_set)} setOnce=${JSON.stringify(setOnceOf(update))} unset=${JSON.stringify(update.properties_to_unset)} -> ${row && row.version === update.version ? 'lands' : 'conflict'}`
        )
        if (!row || row.team_id !== update.team_id || row.version !== update.version) {
            return this.deliver(this.holdWrites, `cas:${update.uuid}`, [undefined, []] as const, () => undefined)
        }
        const lanes = { ...setOnceOf(update), ...update.properties_to_set }
        if (
            Object.keys(lanes).length === 0 &&
            update.properties_to_unset.length === 0 &&
            update.is_identified === row.is_identified &&
            (update.last_seen_at?.toMillis() ?? null) === (row.last_seen_at?.toMillis() ?? null)
        ) {
            this.idleWrites.push(`${update.uuid} v${row.version}`)
        }
        this.noteReplays(row, this.filling(row, update))
        const properties = { ...update.properties }
        for (const [key, value] of Object.entries(setOnceOf(update))) {
            if (!Object.hasOwn(properties, key)) {
                properties[key] = value
            }
        }
        Object.assign(properties, update.properties_to_set)
        for (const key of update.properties_to_unset) {
            delete properties[key]
        }
        row.properties = properties
        row.is_identified = update.is_identified
        row.last_seen_at = update.last_seen_at
        row.version += 1
        this.recordCommit(row)
        update.properties_to_unset.forEach((key) => this.recordAbsent(update.uuid, key))
        this.noteLanded(row, [...Object.keys(lanes), ...update.properties_to_unset])
        const written = this.snapshot(row)
        return this.deliver(this.holdWrites, `cas:${update.uuid}`, [row.version, []] as const, () =>
            this.observePerson(written)
        )
    })
    handleOversizedPersonProperties = jest.fn()
    personPropertiesSize = jest.fn().mockResolvedValue(0)
    fetchPersonDistinctIdMappings = jest.fn().mockResolvedValue([])
    inTransaction = jest.fn(async (_description: string, body: (tx: unknown) => Promise<unknown>) => body({}))

    /** The merge's statement as the transaction: the merge holds the row locks, so it answers at once. */
    tx = {
        updatePersonsBatch: (updates: PersonUpdate[]) => {
            const held = this.holdWrites
            this.holdWrites = false
            try {
                return this.updatePersonsBatch(updates)
            } finally {
                this.holdWrites = held
            }
        },
    } as unknown as PersonRepositoryTransaction

    private lookup(teamId: number, distinctId: string): InternalPerson | undefined {
        const uuid = this.distinctToUuid.get(`${teamId}:${distinctId}`)
        const row = uuid === undefined ? undefined : this.rows.get(uuid)
        return row ? this.snapshot(row) : undefined
    }

    private snapshot(row: InternalPerson): InternalPerson {
        return { ...row, properties: { ...row.properties } }
    }

    /** The values a per-key write changes: its sets, and its set-once values where the row lacks the key. */
    private filling(row: InternalPerson, update: PersonUpdate): Record<string, unknown> {
        const fills = Object.fromEntries(
            Object.entries(setOnceOf(update)).filter(([key]) => !Object.hasOwn(row.properties, key))
        )
        return { ...fills, ...update.properties_to_set }
    }

    /** Exact while the driver never re-sets a value: a value landed on this row before is a replay. */
    private noteReplays(row: InternalPerson, carried: Record<string, unknown>): void {
        const seen = this.podLandedValues.get(row.uuid) ?? new Map<string, unknown[]>()
        this.podLandedValues.set(row.uuid, seen)
        for (const [key, value] of Object.entries(carried)) {
            const before = seen.get(key) ?? []
            const again = before.some((previous) => isEqual(previous, value))
            before.push(value)
            seen.set(key, before)
            if (again && !isEqual(row.properties[key], value)) {
                this.replayed.push(
                    `${row.uuid}.${key}=${JSON.stringify(value)} over ${JSON.stringify(row.properties[key])}`
                )
            }
        }
    }

    private recordCommit(row: InternalPerson): void {
        const at = ++this.clock
        const history = this.committed.get(row.uuid) ?? new Map<string, { value: unknown; at: number }[]>()
        for (const [key, value] of Object.entries(row.properties)) {
            const values = history.get(key) ?? []
            if (values.length === 0 || !isEqual(values[values.length - 1].value, value)) {
                values.push({ value, at })
            }
            history.set(key, values)
        }
        for (const [key, values] of history) {
            if (!Object.hasOwn(row.properties, key) && values[values.length - 1].value !== undefined) {
                values.push({ value: undefined, at })
            }
        }
        this.committed.set(row.uuid, history)
    }

    /** An unset of a key the row never held still counts as the key being absent afterwards. */
    private recordAbsent(uuid: string, key: string): void {
        const history = this.committed.get(uuid) ?? new Map<string, { value: unknown; at: number }[]>()
        const values = history.get(key) ?? []
        if (values.length === 0 || values[values.length - 1].value !== undefined) {
            values.push({ value: undefined, at: ++this.clock })
        }
        history.set(key, values)
        this.committed.set(uuid, history)
    }

    private noteLanded(row: InternalPerson, keys: string[]): void {
        const landed = this.podLanded.get(row.uuid) ?? new Map<string, Landing>()
        const carried = this.podCarried.get(row.uuid) ?? new Set<string>()
        for (const key of keys) {
            landed.set(key, { value: row.properties[key], seq: ++this.seq, version: row.version })
            carried.add(key)
        }
        this.podLanded.set(row.uuid, landed)
        this.podCarried.set(row.uuid, carried)
    }

    private noteOtherPod(uuid: string, key: string, value: unknown): void {
        const last = this.otherPodLast.get(uuid) ?? new Map<string, unknown>()
        last.set(key, value)
        this.otherPodLast.set(uuid, last)
    }

    private observe(uuid: string, snapshot: RowSnapshot): void {
        const current = this.newestDelivered.get(uuid)
        if (!current || snapshot.version > current.version) {
            this.newestDelivered.set(uuid, { version: snapshot.version, properties: { ...snapshot.properties } })
        }
    }

    private observePerson(person: InternalPerson | undefined): void {
        if (person) {
            this.observe(person.uuid, { version: person.version, properties: person.properties })
        }
    }

    private fail(hold: boolean, label: string, error: Error): Promise<never> {
        if (!hold) {
            return Promise.reject(error)
        }
        return new Promise((_, reject) => this.held.push({ label, deliver: () => reject(error) }))
    }

    private deliver<T>(hold: boolean, label: string, value: T, onDeliver: () => void): Promise<T> {
        const answer = (): void => {
            this.writes.push(`answer@${this.step} ${label}`)
            onDeliver()
        }
        if (!hold) {
            answer()
            return Promise.resolve(value)
        }
        return new Promise((resolve) =>
            this.held.push({
                label,
                deliver: () => {
                    answer()
                    resolve(value)
                },
            })
        )
    }

    private noteRead(label: string, persons: (InternalPerson | undefined)[]): void {
        const rows = persons.flatMap((person) => (person ? [`${person.uuid} v${person.version}`] : []))
        this.writes.push(`read@${this.step} ${label} -> ${rows.join(', ') || 'none'}`)
    }
}

/**
 * Drift: keys where the view differs from the newest row the store has received, pending keys
 * aside. Another pod's value that arrived in a row this pod's own write returned counts, so this
 * measures the versioned-base design's promise, which the branch does not make.
 */
function viewDrift(store: BatchWritingPersonsStore, fake: FakePersonRepository): string[] {
    const disagreements: string[] = []
    for (const row of fake.rows.values()) {
        const entry = store.getCachedPersonForUpdateByPersonId(row.team_id, row.id)
        const seen = fake.newestDelivered.get(row.uuid)
        if (!entry || !seen) {
            continue
        }
        const view = toInternalPerson(entry).properties
        const pending = new Set([
            ...Object.keys(entry.properties_to_set),
            ...Object.keys(setOnceOf(entry)),
            ...entry.properties_to_unset,
        ])
        for (const key of new Set([...Object.keys(view), ...Object.keys(seen.properties)])) {
            if (pending.has(key) || isEqual(view[key], seen.properties[key])) {
                continue
            }
            disagreements.push(
                `${row.uuid}.${key}: view=${JSON.stringify(view[key])} row@v${seen.version}=${JSON.stringify(seen.properties[key])}`
            )
        }
    }
    return disagreements
}

/**
 * For each key this pod wrote and has nothing pending for, the view shows the value this pod's newest
 * landed write left in the row, or the value in a newer row the store has received since.
 */
function cacheRowDisagreements(store: BatchWritingPersonsStore, fake: FakePersonRepository): string[] {
    const disagreements: string[] = []
    for (const row of fake.rows.values()) {
        const entry = store.getCachedPersonForUpdateByPersonId(row.team_id, row.id)
        const landed = fake.podLanded.get(row.uuid)
        if (!entry || !landed) {
            continue
        }
        const view = toInternalPerson(entry).properties
        const pending = new Set([
            ...Object.keys(entry.properties_to_set),
            ...Object.keys(setOnceOf(entry)),
            ...entry.properties_to_unset,
        ])
        const seen = fake.newestDelivered.get(row.uuid)
        for (const [key, landing] of landed) {
            const expected = seen && seen.version >= landing.version ? seen.properties[key] : landing.value
            if (pending.has(key) || isEqual(view[key], expected)) {
                continue
            }
            disagreements.push(
                `${row.uuid}.${key}: view=${JSON.stringify(view[key])} expected=${JSON.stringify(expected)}`
            )
        }
    }
    return disagreements
}

function mulberry32(seed: number): () => number {
    let state = seed >>> 0
    return () => {
        state = (state + 0x6d2b79f5) >>> 0
        let t = state
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

const setOps = (set: Record<string, unknown>, forced = true, unset: string[] = []): EventOps => ({
    set,
    setOnce: {},
    unset,
    denied: false,
    shouldForceUpdate: forced,
    eventName: '$set',
})

const RESETS = process.env.MODEL_RESETS === '1'
const ASSERT = process.env.MODEL_MODE === 'assert'
/** Ablation of the per-key statement: the fake applies every write as master's full snapshot. */
const SNAPSHOT_SQL = process.env.MODEL_SQL === 'snapshot'

// The version-checked mode sleeps a millisecond between retries, so its ticks wait out that timer to stay deterministic.
const tick = (): Promise<void> =>
    ASSERT ? new Promise((resolve) => setTimeout(resolve, 2)) : new Promise((resolve) => setImmediate(resolve))

/** A key the update filter skips unless the event forces the write or the key is new on the person. */
const FILTERED_KEY = [...FILTERED_PERSON_UPDATE_PROPERTIES][0]

const outputs = () =>
    createMockIngestionOutputs<
        PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
    >()

type SeedResult = {
    log: string[]
    disagreements: string[]
    leftoverPending: string[]
    lost: string[]
    drift: string[]
    replayed: string[]
    erased: string[]
    idle: string[]
    leaks: string[]
    dump: string[]
}

/** A read the store began and never ended keeps the drop record growing for the life of the process. */
function readsLeftInFlight(store: BatchWritingPersonsStore): string[] {
    const size = (store as unknown as { personCache: { readsInFlight: Map<number, number> } }).personCache.readsInFlight
        .size
    return size > 0 ? [`${size} reads left in flight`] : []
}

/** Another pod's last write to a key this pod never carried on that row must still stand. */
function erasedByThisPod(fake: FakePersonRepository): string[] {
    const erased: string[] = []
    for (const row of fake.rows.values()) {
        const carried = fake.podCarried.get(row.uuid) ?? new Set<string>()
        for (const [key, value] of fake.otherPodLast.get(row.uuid) ?? []) {
            if (!carried.has(key) && !isEqual(row.properties[key], value)) {
                erased.push(
                    `${row.uuid}.${key}: row=${JSON.stringify(row.properties[key])} other=${JSON.stringify(value)}`
                )
            }
        }
    }
    return erased
}

/** Rows, their commit history, what this pod landed, and every cache entry, for reading one seed by hand. */
function dumpState(store: BatchWritingPersonsStore, fake: FakePersonRepository): string[] {
    const lines: string[] = []
    for (const row of fake.rows.values()) {
        lines.push(`row ${row.uuid} id=${row.id} v${row.version} ${JSON.stringify(row.properties)}`)
    }
    for (const [uuid, history] of fake.committed) {
        for (const [key, values] of history) {
            lines.push(`history ${uuid}.${key}: ${values.map(({ value }) => JSON.stringify(value)).join(' > ')}`)
        }
    }
    for (const [uuid, landed] of fake.podLanded) {
        for (const [key, { value, seq }] of landed) {
            lines.push(`landed ${uuid}.${key}=${JSON.stringify(value)} #${seq}`)
        }
    }
    lines.push(...fake.writes)
    for (const [cacheKey, entry] of store.getUpdateCache()) {
        if (!entry) {
            lines.push(`entry ${cacheKey}: null`)
            continue
        }
        lines.push(
            `entry ${cacheKey} uuid=${entry.uuid} view=${JSON.stringify(toInternalPerson(entry).properties)} set=${JSON.stringify(entry.properties_to_set)} setOnce=${JSON.stringify(setOnceOf(entry))} unset=${JSON.stringify(entry.properties_to_unset)} dirty=${entry.needs_write} identified=${entry.is_identified}/${entry.original_is_identified} v${entry.version}`
        )
    }
    return lines
}

/**
 * One seeded interleaving: this pod's events, prefetches and flushes against other pods' writes and
 * merges, with held answers released in random order. Flushes never overlap, as in the pipeline.
 */
async function runSeed(seed: number, steps: number, log: string[]): Promise<SeedResult> {
    const rand = mulberry32(seed)
    const pick = <T>(items: T[]): T => items[Math.floor(rand() * items.length)]
    const fake = new FakePersonRepository()
    const store = new BatchWritingPersonsStore(fake as unknown as PersonRepository, outputs(), {
        dbWriteMode: ASSERT ? 'ASSERT_VERSION' : 'NO_ASSERT',
        optimisticUpdateRetryInterval: 1,
    })
    const distinctIds: Record<string, string[]> = { P1: ['a1', 'a2'], P2: ['b1', 'b2'], P3: ['c1', 'c2'] }
    for (const [uuid, ids] of Object.entries(distinctIds)) {
        fake.addPerson(uuid, ids, { k1: 'seed' })
    }
    const allIds = Object.values(distinctIds).flat()
    const keys = ['k1', 'k2', FILTERED_KEY]
    const outstanding: Promise<unknown>[] = []
    const intents: {
        distinctId: string
        uuid: string
        key: string
        value: string | undefined
        window: number
        optional: boolean
        carried?: number
    }[] = []
    let flushesInFlight = 0
    let batch = 0
    for (let step = 0; step < steps; step++) {
        fake.step = step
        const op = pick([
            'event',
            'event',
            'event',
            'unset',
            'otherPod',
            'otherUnset',
            'mergeAway',
            'podMerge',
            'prefetch',
            'flush',
            'release',
            'release',
            'fetchError',
        ])
        if (op === 'fetchError') {
            // One read fails as a transient repository error, consumed here so it cannot fail a flush's re-target,
            // which the pipeline would answer by retrying the whole batch.
            const distinctId = pick(allIds)
            const heldPrefetch = fake.labels().indexOf(`prefetch:${distinctId}`)
            if (heldPrefetch >= 0) {
                fake.release(heldPrefetch)
            }
            fake.fetchFailures = 1
            const person = await store.fetchForUpdate(1, distinctId, batch).catch(() => undefined)
            fake.fetchFailures = 0
            log.push(person ? `read ${distinctId} served from cache` : `read failed ${distinctId}`)
        } else if (op === 'unset') {
            const distinctId = pick(allIds)
            const heldPrefetch = fake.labels().indexOf(`prefetch:${distinctId}`)
            if (heldPrefetch >= 0) {
                log.push(`release prefetch:${distinctId}`)
                fake.release(heldPrefetch)
            }
            const person = await store.fetchForUpdate(1, distinctId, batch).catch(() => undefined)
            if (!person) {
                log.push(`read failed ${distinctId}`)
                await tick()
                continue
            }
            const key = pick(keys)
            await store.applyEventOps(person, setOps({}, true, [key]), distinctId, batch)
            // An unset of a key the view does not hold is a no-op by design.
            const optional = !Object.hasOwn(person!.properties, key)
            intents.push({ distinctId, uuid: person!.uuid, key, value: undefined, window: batch, optional })
            log.push(`unset ${distinctId} ${key}`)
        } else if (op === 'otherUnset') {
            const uuid = pick([...fake.rows.keys()])
            const key = pick(keys)
            fake.otherPodUnset(uuid, key)
            log.push(`other ${uuid} unset ${key}`)
        } else if (op === 'podMerge') {
            // This pod's merge, as the store sees it: the ids move, the outcome is written to the survivor inside
            // the transaction with the carried keys as set-once, the source row goes, and after the commit the
            // survivor's entry takes the row and the source's clears.
            const alive = [...fake.rows.keys()]
            const idOf = (uuid: string): string =>
                [...fake.distinctToUuid].find(([, mapped]) => mapped === uuid)![0].slice(2)
            // The merge resolves both persons through the store; a stale entry there makes it read a missing
            // row at delete and retry, so the driver only merges what the store and the rows agree on.
            const fresh = async (uuid: string): Promise<boolean> => {
                const distinctId = idOf(uuid)
                const heldPrefetch = fake.labels().indexOf(`prefetch:${distinctId}`)
                if (heldPrefetch >= 0) {
                    log.push(`release prefetch:${distinctId}`)
                    fake.release(heldPrefetch)
                }
                const person = await store.fetchForUpdate(1, distinctId, batch).catch(() => undefined)
                return person?.uuid === uuid
            }
            if (alive.length > 1 && (await fresh(alive[0])) && (await fresh(alive[1]))) {
                const sourceUuid = pick(alive.slice(0, 2))
                const targetUuid = alive.slice(0, 2).find((uuid) => uuid !== sourceUuid)!
                const source = fake.rows.get(sourceUuid)!
                const target = fake.rows.get(targetUuid)!
                const sourceIds = [...fake.distinctToUuid]
                    .filter(([, uuid]) => uuid === sourceUuid)
                    .map(([key]) => key.slice(key.indexOf(':') + 1))
                const sourcePending = store.pendingChanges(1, source.id)
                const view = (
                    row: InternalPerson,
                    pending = store.pendingChanges(1, row.id)
                ): Record<string, unknown> => {
                    const merged = { ...pending?.toSetOnce, ...row.properties, ...pending?.toSet }
                    pending?.toUnset.forEach((key) => delete merged[key])
                    return merged
                }
                const targetView = view(target)
                const sourceView = view(source, sourcePending)
                const carried = Object.fromEntries(
                    Object.entries(sourceView).filter(([key]) => !Object.hasOwn(targetView, key))
                )
                // The survivor's value wins, so the source's unflushed changes to keys it holds are dropped by
                // design; the rest move to the survivor as gap-fills.
                for (const intent of intents) {
                    // A gap the survivor's own pending unset left is filled from the source, superseding the unset.
                    if (
                        intent.uuid === targetUuid &&
                        intent.value === undefined &&
                        Object.hasOwn(carried, intent.key)
                    ) {
                        intent.optional = true
                    }
                    if (intent.uuid !== sourceUuid) {
                        continue
                    }
                    intent.uuid = targetUuid
                    if (Object.hasOwn(targetView, intent.key)) {
                        intent.optional = true
                    } else if (Object.hasOwn(carried, intent.key)) {
                        intent.carried = fake.clock
                    }
                }
                const targetDistinctId = idOf(targetUuid)
                // The merge sees the target as this pod does: the row with its pending changes applied.
                const targetEntry = store.getCachedPersonForUpdateByPersonId(1, target.id)
                const targetPerson = targetEntry
                    ? toInternalPerson(targetEntry)
                    : { ...target, properties: { ...target.properties } }
                // A key the survivor's pending unset hides goes as a set, as the merge does, or the unset would win.
                const targetPending = store.pendingChanges(1, target.id)
                const hidden = new Set(targetPending?.toUnset ?? [])
                const outcome: MergePersonUpdate = {
                    properties: Object.fromEntries(Object.entries(carried).filter(([key]) => hidden.has(key))),
                    properties_to_set_once: Object.fromEntries(
                        Object.entries(carried).filter(([key]) => !hidden.has(key))
                    ),
                    is_identified: true,
                }
                await store.moveDistinctIds(
                    { ...source },
                    targetPerson,
                    targetDistinctId,
                    undefined,
                    fake as unknown as Parameters<typeof store.moveDistinctIds>[4],
                    batch
                )
                const [row, , written] = await store.updatePersonForMerge(
                    targetPerson,
                    outcome,
                    targetDistinctId,
                    fake.tx
                )
                log.push(`podMerge ${sourceUuid}->${targetUuid} carried=${Object.keys(carried).join(',') || '-'}`)
                // A read of a moved id that began before the merge returns the source until the commit, so an event on
                // that id can reach the source's entry after the merge read its pending changes.
                const heldRead = sourceIds
                    .map((distinctId) => ({ distinctId, index: fake.labels().indexOf(`prefetch:${distinctId}`) }))
                    .find(({ index }) => index >= 0)
                if (heldRead) {
                    log.push(`release prefetch:${heldRead.distinctId}`)
                    fake.release(heldRead.index)
                    const person = await store.fetchForUpdate(1, heldRead.distinctId, batch)
                    const key = pick(keys)
                    const value = `m${step}`
                    await store.applyEventOps(person!, setOps({ [key]: value }), heldRead.distinctId, batch)
                    // Recorded on the entry that took it, where a later event on the same id supersedes it.
                    const landedOn = store.pendingChanges(1, source.id)?.toSet[key] === value ? sourceUuid : targetUuid
                    intents.push({
                        distinctId: heldRead.distinctId,
                        uuid: landedOn,
                        key,
                        value,
                        window: batch,
                        optional: false,
                    })
                    log.push(`event ${heldRead.distinctId} ${key}=${value} on ${landedOn} before the release`)
                }
                fake.rows.delete(sourceUuid)
                if (written) {
                    store.takeMergedRow(row, targetDistinctId, outcome, targetPending, batch)
                }
                store.releaseMergedSource(1, source.id, sourcePending)
            }
        } else if (op === 'event') {
            const distinctId = pick(allIds)
            // An update read waits on a held prefetch of the same id, and the driver could not release it while waiting.
            const heldPrefetch = fake.labels().indexOf(`prefetch:${distinctId}`)
            if (heldPrefetch >= 0) {
                log.push(`release prefetch:${distinctId}`)
                fake.release(heldPrefetch)
            }
            const person = await store.fetchForUpdate(1, distinctId, batch).catch(() => undefined)
            if (!person) {
                log.push(`read failed ${distinctId}`)
                await tick()
                continue
            }
            const key = pick(keys)
            const forced = pick([true, true, false])
            // With MODEL_RESETS, sometimes a value the key held before, so a change can go back to an earlier
            // value; the replay oracle is then off, because a re-set and a replay look the same by value.
            const earlier = intents
                .filter((intent) => intent.key === key && intent.value !== undefined)
                .map((intent) => intent.value as string)
            const value = RESETS && earlier.length > 0 && rand() < 0.25 ? pick(earlier) : `e${step}`
            await store.applyEventOps(person!, setOps({ [key]: value }, forced), distinctId, batch)
            // An unforced change to a filtered key writes nothing on its own, so it may never land.
            const optional = !forced && key === FILTERED_KEY
            intents.push({ distinctId, uuid: person!.uuid, key, value, window: batch, optional })
            log.push(`event${forced ? '' : ' (unforced)'} ${distinctId} ${key}=${value}`)
        } else if (op === 'otherPod') {
            const uuid = pick([...fake.rows.keys()])
            const key = pick(keys)
            fake.otherPodSet(uuid, { [key]: `o${step}` })
            log.push(`other ${uuid} ${key}=o${step}`)
        } else if (op === 'mergeAway') {
            const alive = [...fake.rows.keys()]
            if (alive.length > 1) {
                const source = pick(alive)
                const target = pick(alive.filter((uuid) => uuid !== source))
                fake.mergeAway(source, target)
                log.push(`merge ${source}->${target}`)
            }
        } else if (op === 'prefetch') {
            const distinctId = pick(allIds)
            fake.holdFetches = true
            outstanding.push(store.prefetchPersons([{ teamId: 1, distinctId, batchId: batch + 1 }]))
            fake.holdFetches = false
            log.push(`prefetch ${distinctId}`)
        } else if (op === 'flush') {
            if (flushesInFlight === 0) {
                const flushed = batch
                batch++
                flushesInFlight++
                fake.holdWrites = true
                // The pipeline releases a batch once its flush completes, which is when eviction runs.
                outstanding.push(
                    store.flush().finally(() => {
                        flushesInFlight--
                        store.releaseBatch(flushed)
                    })
                )
                log.push('flush')
            }
        } else if (fake.held.length > 0) {
            const index = Math.floor(rand() * fake.held.length)
            log.push(`release ${fake.labels()[index]}`)
            fake.release(index)
        }
        await tick()
    }
    fake.holdWrites = false
    fake.holdFetches = false
    while (fake.held.length > 0 || flushesInFlight > 0) {
        fake.releaseAll()
        await tick()
    }
    await Promise.all(outstanding)
    await store.flush()
    const disagreements = cacheRowDisagreements(store, fake)
    const leftoverPending: string[] = []
    for (const row of fake.rows.values()) {
        const entry = store.getCachedPersonForUpdateByPersonId(row.team_id, row.id)
        if (!entry) {
            continue
        }
        const pending = [
            ...Object.keys(entry.properties_to_set),
            ...Object.keys(setOnceOf(entry)),
            ...entry.properties_to_unset,
        ].filter((key) => key !== FILTERED_KEY)
        if (pending.length > 0) {
            leftoverPending.push(`${row.uuid} pending ${pending.join(',')}`)
        }
    }
    // Sets of one key on one person coalesce, so only the last per person and key must have reached
    // some row at some point, whatever overwrote it later.
    const histories = [...fake.committed.values()]
    const lastPerGroup = new Map<string, (typeof intents)[number]>()
    for (const intent of intents) {
        lastPerGroup.set(`${intent.uuid}|${intent.key}`, intent)
    }
    // A gap-fill that another pod's value beat to the row is a race, not a loss; a gap nobody filled after the
    // merge is a loss. An unset is also satisfied when the person the id now names simply lacks the key.
    const heldSince = (uuid: string, key: string, since: number): boolean =>
        (fake.committed.get(uuid)?.get(key) ?? []).some(({ value, at }) => value !== undefined && at >= since)
    const rowFor = (uuid: string, distinctId: string): InternalPerson | undefined =>
        fake.rows.get(uuid) ?? fake.rows.get(fake.distinctToUuid.get(`1:${distinctId}`) ?? '')
    const lost = [...lastPerGroup.values()]
        .filter(({ optional }) => !optional)
        .filter(
            ({ key, value }) =>
                !histories.some((history) => history.get(key)?.some((held) => isEqual(held.value, value)))
        )
        .filter(({ key, value, uuid, distinctId }) => {
            const row = rowFor(uuid, distinctId)
            return !(value === undefined && row !== undefined && !Object.hasOwn(row.properties, key))
        })
        .filter(
            ({ carried, uuid, key, distinctId }) =>
                carried === undefined || !heldSince(rowFor(uuid, distinctId)?.uuid ?? uuid, key, carried)
        )
        .map(({ distinctId, key, value }) => `lost ${key}=${value} (event ${distinctId})`)
    const drift = viewDrift(store, fake)
    const erased = erasedByThisPod(fake)
    const leaks = readsLeftInFlight(store)
    const dump = dumpState(store, fake)
    dump.push(
        ...intents.map(
            (intent) =>
                `intent ${intent.distinctId}->${intent.uuid} ${intent.key}=${intent.value} w${intent.window}${intent.optional ? ' optional' : ''}${intent.carried === undefined ? '' : ` carried@${intent.carried}`}`
        )
    )
    await store.shutdown().catch(() => undefined)
    return {
        log,
        disagreements,
        leftoverPending,
        lost,
        drift,
        replayed: [...fake.replayed],
        erased,
        idle: [...fake.idleWrites],
        leaks,
        dump,
    }
}

describe('BatchWritingPersonsStore against a row model', () => {
    let fake: FakePersonRepository
    let store: BatchWritingPersonsStore

    beforeEach(() => {
        fake = new FakePersonRepository()
        store = new BatchWritingPersonsStore(
            fake as unknown as PersonRepository,
            createMockIngestionOutputs<
                PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
            >()
        )
    })

    afterEach(async () => {
        fake.holdWrites = false
        fake.holdFetches = false
        fake.releaseAll()
        try {
            await store.flush()
        } catch {
            // a test may leave a write that cannot land
        }
        try {
            await store.shutdown()
        } catch {
            // a test may leave the cache dirty
        }
    })

    it("a source's write re-targeted after the survivor's own write leaves the survivor's view on the row", async () => {
        fake.addPerson('T', ['t'], {})
        fake.addPerson('S', ['s'], {})
        const target = await store.fetchForUpdate(1, 't', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(target!, { k: 'B' }, [], {}, 't')
        const source = await store.fetchForUpdate(1, 's', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(source!, { k: 'A' }, [], {}, 's')
        fake.mergeAway('S', 'T')

        await store.flush()

        expect(fake.rows.get('T')!.properties).toEqual({ k: 'A' })
        expect(cacheRowDisagreements(store, fake)).toEqual([])
    })

    it('a read through a new distinct id answers the view this pod holds under another', async () => {
        fake.addPerson('P', ['d1', 'd2'], {})
        const person = await store.fetchForUpdate(1, 'd1', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(person!, { k: 'A' }, [], {}, 'd1')

        expect((await store.fetchForUpdate(1, 'd2', 0))!.properties).toEqual({ k: 'A' })
    })

    it('an unforced repeat of a pending value leaves the entry clean', async () => {
        fake.addPerson('P', ['d1'], { [FILTERED_KEY]: 'old' })
        const person = await store.fetchForUpdate(1, 'd1', 0)
        await store.applyEventOps(person!, setOps({ [FILTERED_KEY]: 'x' }, false), 'd1', 0)
        await store.flush()
        await store.applyEventOps(
            (await store.fetchForUpdate(1, 'd1', 0))!,
            setOps({ [FILTERED_KEY]: 'x' }, false),
            'd1',
            0
        )

        expect(store.getCachedPersonForUpdateByPersonId(1, person!.id)?.needs_write).toBe(false)
    })

    it('a forced $set of a value an unforced event left pending writes it', async () => {
        fake.addPerson('P', ['d1'], { [FILTERED_KEY]: 'old' })
        const person = await store.fetchForUpdate(1, 'd1', 0)
        await store.applyEventOps(person!, setOps({ [FILTERED_KEY]: 'x' }, false), 'd1', 0)
        await store.applyEventOps((await store.fetchForUpdate(1, 'd1', 0))!, setOps({ [FILTERED_KEY]: 'x' }), 'd1', 0)

        await store.flush()

        expect(fake.rows.get('P')!.properties).toEqual({ [FILTERED_KEY]: 'x' })
    })

    it("a fetch that read the row before this pod's write landed does not put the old value back", async () => {
        fake.addPerson('P', ['d1', 'd2'], { k: 'old' })
        const person = await store.fetchForUpdate(1, 'd1', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(person!, { k: 'new' }, [], {}, 'd1')
        fake.holdFetches = true
        const prefetching = store.prefetchPersons([{ teamId: 1, distinctId: 'd2', batchId: 1 }])
        expect(fake.labels()).toEqual(['prefetch:d2'])

        await store.flush()
        fake.releaseAll()
        await prefetching

        expect(fake.rows.get('P')!.properties).toEqual({ k: 'new' })
        expect(cacheRowDisagreements(store, fake)).toEqual([])
    })

    it("a row read that arrives while this pod's write answer is out leaves nothing for the next flush to send", async () => {
        fake.addPerson('P', ['d1', 'd2'], {})
        const person = await store.fetchForUpdate(1, 'd1', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(person!, {}, [], { is_identified: true }, 'd1')
        fake.holdWrites = true
        const flushing = store.flush()
        await fake.settle(() => fake.labels().length === 1)
        // The row already holds the write; a read of it through another id lands before the answer does.
        await store.prefetchPersons([{ teamId: 1, distinctId: 'd2', batchId: 1 }])
        fake.releaseAll()
        await flushing
        fake.holdWrites = false
        // A repeat identify changes nothing the row does not already hold.
        await store.updatePersonWithPropertiesDiffForUpdate(person!, {}, [], { is_identified: true }, 'd1')

        await store.flush()

        expect(fake.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(cacheRowDisagreements(store, fake)).toEqual([])
    })

    it('a re-targeted write carries the last_seen_at an event advanced on the live entry after the flush snapshot', async () => {
        const seen = DateTime.fromISO('2026-01-02T00:00:00Z', { zone: 'utc' })
        fake.addPerson('T', ['t'], {})
        fake.addPerson('S', ['s'], {})
        await store.fetchForUpdate(1, 't', 0)
        const source = await store.fetchForUpdate(1, 's', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(source!, { k: 'A' }, [], {}, 's')
        fake.mergeAway('S', 'T')
        fake.holdWrites = true
        const flushing = store.flush()
        await fake.settle(() => fake.labels().length === 1)
        await store.updatePersonWithPropertiesDiffForUpdate(source!, {}, [], { last_seen_at: seen }, 's')
        fake.holdWrites = false
        fake.releaseAll()
        await flushing

        expect(fake.rows.get('T')!.last_seen_at?.toISO()).toBe(seen.toISO())
        expect(cacheRowDisagreements(store, fake)).toEqual([])
    })

    /** The merge's survivor write under its transaction, and the survivor's entry taking the row at the commit. */
    const mergeInto = async (
        target: InternalPerson,
        update: MergePersonUpdate,
        distinctId: string
    ): Promise<() => void> => {
        const read = store.pendingChanges(1, target.id)
        const [row, , written] = await store.updatePersonForMerge(target, update, distinctId, fake.tx)
        return () => {
            if (written) {
                store.takeMergedRow(row, distinctId, update, read, 0)
            }
        }
    }

    it("an event that reaches a source's entry after the merge read its pending changes lands on the survivor", async () => {
        fake.addPerson('S', ['s1', 's2'], {})
        fake.addPerson('T', ['t'], {})
        const source = await store.fetchForUpdate(1, 's1', 0)
        const target = await store.fetchForUpdate(1, 't', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(source!, { k: 'early' }, [], {}, 's1')
        // A read of s2 that began before the merge returns the source until the commit.
        fake.holdFetches = true
        const reading = store.fetchForUpdate(1, 's2', 0)
        fake.holdFetches = false
        // The merge as person-merge-postgres orders it: move, read the pending changes, write the survivor,
        // delete, commit, take the row, release.
        await store.moveDistinctIds(
            source!,
            target!,
            't',
            undefined,
            fake as unknown as Parameters<typeof store.moveDistinctIds>[4],
            0
        )
        const read = store.pendingChanges(1, source!.id)
        const committed = await mergeInto(target!, { properties_to_set_once: read!.toSet, is_identified: true }, 't')
        fake.releaseAll()
        const stale = await reading
        expect(stale!.uuid).toBe('S')
        await store.applyEventOps(stale!, setOps({ j: 'late' }), 's2', 0)
        fake.rows.delete('S')
        committed()
        store.releaseMergedSource(1, source!.id, read)
        // The leftover waits for the re-target, but the moved id already reads the survivor.
        expect((await store.fetchForUpdate(1, 's2', 0))!.uuid).toBe('T')

        await store.flush()

        expect(fake.rows.get('T')!.properties).toEqual({ k: 'early', j: 'late' })
        expect(cacheRowDisagreements(store, fake)).toEqual([])
    })

    it('a read of a moved id that answers after the release does not bring the source back', async () => {
        fake.addPerson('S', ['s1', 's2', 's3'], {})
        fake.addPerson('T', ['t'], {})
        const source = await store.fetchForUpdate(1, 's1', 0)
        const target = await store.fetchForUpdate(1, 't', 0)
        fake.holdFetches = true
        const readingS2 = store.fetchForUpdate(1, 's2', 0)
        const readingS3 = store.fetchForUpdate(1, 's3', 0)
        fake.holdFetches = false
        await store.moveDistinctIds(
            source!,
            target!,
            't',
            undefined,
            fake as unknown as Parameters<typeof store.moveDistinctIds>[4],
            0
        )
        const read = store.pendingChanges(1, source!.id)
        const committed = await mergeInto(target!, { is_identified: true }, 't')
        // One read answers inside the window and carries an event onto the source's entry, so the release keeps
        // it; the other answers after the release.
        fake.release(0)
        await store.applyEventOps((await readingS2)!, setOps({ j: 'late' }), 's2', 0)
        fake.rows.delete('S')
        committed()
        store.releaseMergedSource(1, source!.id, read)
        fake.releaseAll()

        expect((await readingS3)!.uuid).toBe('T')
    })

    it.each([
        [
            'nobody owns its distinct id',
            setOps({ j: 'late' }),
            (fake: FakePersonRepository) => fake.distinctToUuid.delete('1:s1'),
        ],
        ['the flush would not write it', setOps({ [FILTERED_KEY]: 'x' }, false), () => undefined],
    ])('a kept source entry is evicted once %s', async (_case, leftover, arrange) => {
        // A changed filtered key is a leftover the flush ignores; a new one would write.
        fake.addPerson('S', ['s1', 's2'], { [FILTERED_KEY]: 'old' })
        fake.addPerson('T', ['t'], {})
        const source = await store.fetchForUpdate(1, 's1', 0)
        const target = await store.fetchForUpdate(1, 't', 0)
        fake.holdFetches = true
        const reading = store.fetchForUpdate(1, 's2', 0)
        fake.holdFetches = false
        await store.moveDistinctIds(
            source!,
            target!,
            't',
            undefined,
            fake as unknown as Parameters<typeof store.moveDistinctIds>[4],
            0
        )
        const read = store.pendingChanges(1, source!.id)
        const committed = await mergeInto(target!, { is_identified: true }, 't')
        fake.releaseAll()
        await store.applyEventOps((await reading)!, leftover, 's2', 0)
        fake.rows.delete('S')
        committed()
        store.releaseMergedSource(1, source!.id, read)
        arrange(fake)

        await store.flush()

        expect(store.getCachedPersonForUpdateByPersonId(1, source!.id)).toBeUndefined()
    })

    it("a merge's release drops a source's entry once every change it held is carried", async () => {
        fake.addPerson('S', ['s1'], {})
        fake.addPerson('T', ['t'], {})
        const source = await store.fetchForUpdate(1, 's1', 0)
        const target = await store.fetchForUpdate(1, 't', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(source!, { k: 'early' }, [], {}, 's1')
        await store.moveDistinctIds(
            source!,
            target!,
            't',
            undefined,
            fake as unknown as Parameters<typeof store.moveDistinctIds>[4],
            0
        )
        const read = store.pendingChanges(1, source!.id)
        const committed = await mergeInto(target!, { properties_to_set_once: read!.toSet, is_identified: true }, 't')
        fake.rows.delete('S')
        committed()

        store.releaseMergedSource(1, source!.id, read)

        expect(store.getCachedPersonForUpdateByPersonId(1, source!.id)).toBeUndefined()
    })

    it("two sources re-targeted onto one survivor whose results return in reverse order leave the survivor's view on the row", async () => {
        fake.addPerson('T', ['t'], {})
        fake.addPerson('S1', ['s1'], {})
        fake.addPerson('S2', ['s2'], {})
        await store.fetchForUpdate(1, 't', 0)
        const source1 = await store.fetchForUpdate(1, 's1', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(source1!, { k: 'A' }, [], {}, 's1')
        const source2 = await store.fetchForUpdate(1, 's2', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(source2!, { k: 'C' }, [], {}, 's2')
        fake.mergeAway('S1', 'T')
        fake.mergeAway('S2', 'T')
        fake.holdWrites = true

        const flushing = store.flush()
        await fake.settle(() => fake.labels().length === 1)
        fake.release()
        // Both sources fail the batch and retry alone; each retry finds no row.
        await fake.settle(() => fake.labels().length === 2)
        fake.releaseAll()
        // Each refresh re-targets onto T and writes; the second call commits last.
        await fake.settle(() => fake.labels().length === 2)
        const committedLast = fake.rows.get('T')!.properties.k
        fake.release(1)
        fake.release(0)
        await flushing

        expect(fake.rows.get('T')!.properties.k).toBe(committedLast)
        expect(cacheRowDisagreements(store, fake)).toEqual([])
    })

    it('one seed in full, when MODEL_SEED names it', async () => {
        const seed = Number(process.env.MODEL_SEED ?? 0)
        if (seed === 0) {
            return
        }
        const log: string[] = []
        const result = await runSeed(seed, Number(process.env.MODEL_STEPS ?? 24), log)
        process.stdout.write(
            [
                `seed ${seed}`,
                ...log.map((line, index) => `  ${index}: ${line}`),
                ...result.dump.map((line) => `  ${line}`),
                ...result.disagreements.map((line) => `  DISAGREE ${line}`),
                ...result.lost.map((line) => `  LOST ${line}`),
                ...result.drift.map((line) => `  DRIFT ${line}`),
                ...result.replayed.map((line) => `  REPLAY ${line}`),
                ...result.erased.map((line) => `  ERASED ${line}`),
                ...result.idle.map((line) => `  IDLE ${line}`),
                ...result.leaks.map((line) => `  LEAK ${line}`),
                '',
            ].join('\n')
        )
    })

    it('random interleavings leave every cached view on its row once all writes land', async () => {
        const failures: string[] = []
        const byKind = {
            disagreements: 0,
            leftoverPending: 0,
            lost: 0,
            replayed: 0,
            erased: 0,
            idle: 0,
            leaks: 0,
            errors: 0,
            drift: 0,
        }
        const seeds = Number(process.env.MODEL_SEEDS ?? 200)
        const steps = Number(process.env.MODEL_STEPS ?? 24)
        for (let seed = 1; seed <= seeds; seed++) {
            const log: string[] = []
            let problems: string[]
            try {
                const result = await Promise.race([
                    runSeed(seed, steps, log),
                    new Promise<never>((_, reject) => setTimeout(() => reject(new Error('hung')), 10_000).unref()),
                ])
                problems = [
                    ...result.disagreements,
                    ...result.leftoverPending,
                    ...result.lost,
                    ...(RESETS ? [] : result.replayed),
                    ...result.erased,
                    ...result.idle,
                    ...result.leaks,
                ]
                byKind.disagreements += result.disagreements.length > 0 ? 1 : 0
                byKind.leftoverPending += result.leftoverPending.length > 0 ? 1 : 0
                byKind.lost += result.lost.length > 0 ? 1 : 0
                byKind.replayed += result.replayed.length > 0 ? 1 : 0
                byKind.erased += result.erased.length > 0 ? 1 : 0
                byKind.idle += result.idle.length > 0 ? 1 : 0
                byKind.leaks += result.leaks.length > 0 ? 1 : 0
                byKind.drift += result.drift.length > 0 ? 1 : 0
            } catch (error) {
                problems = [String(error)]
                byKind.errors += 1
            }
            if (problems.length > 0) {
                failures.push(`seed ${seed}: ${problems.join('; ')}\n    ${log.join(' | ')}`)
            }
        }
        process.stdout.write(`byKind ${JSON.stringify(byKind)}\n`)
        process.stdout.write(failures.map((failure) => `FAIL ${failure.split('\n')[0]}`).join('\n') + '\n')
        expect({ failing: failures.length, byKind, first: failures.slice(0, 5) }).toEqual({
            failing: 0,
            byKind: {
                disagreements: 0,
                leftoverPending: 0,
                lost: 0,
                replayed: RESETS ? expect.any(Number) : 0,
                erased: 0,
                idle: 0,
                leaks: 0,
                errors: 0,
                drift: expect.any(Number),
            },
            first: [],
        })
    }, 300_000)
})
