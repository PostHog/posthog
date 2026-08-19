import { InternalPerson } from '~/types'

/**
 * One memo edge: the person a distinct id resolves to (null for a
 * known-absent id), and the read class its person state was fetched
 * under. The grade lives on the edge because it describes that edge: an
 * update read went through the leader, a checking read through identity,
 * which the leader leads by writer apply lag — so serving checking-grade
 * state to the update path would hand the property projection a stale
 * baseline. The Postgres store keeps two caches for the same reason.
 */
interface ResolutionEntry {
    personKey: string | null
    grade: 'checking' | 'update'
}

/**
 * The personhog store's shared memo: distinct-id resolution, person
 * projections, read grades, and the per-batch liveness accounting that
 * decides when any of it can be forgotten. One instance serves every
 * open batch, so a merge's purge or repoint reaches all of them at once,
 * as the Postgres cache's does.
 *
 * The memo knows nothing about lanes except what the store's predicate
 * answers: a person with folded, unwritten ops keeps its projection (the
 * batch's read-your-write view) alive regardless of resolution counts,
 * and its state must not be clobbered by fetched snapshots.
 */
export class PersonhogPersonMemo {
    /**
     * Distinct-id resolution, `${teamId}:${distinctId}` to the person key
     * or null for a known-absent id, shared by every open batch. Split
     * from person state so every distinct id of a person reads the same
     * pending projection, not just the one that triggered the update.
     */
    private resolutions: Map<string, ResolutionEntry> = new Map()
    /**
     * Person state keyed by `${teamId}:${personId}`, shared across batches.
     * Once ops fold for a person this holds the pending projection — the
     * read-your-write view — and fetches must not clobber it with service
     * state.
     */
    private personState: Map<string, InternalPerson> = new Map()
    /**
     * How many live resolutions name each person. A projection is the
     * batch's read-your-write view, so it outlives its own lane only while
     * some distinct id still points at it.
     */
    private projectionRefCount: Map<string, number> = new Map()
    /** Distinct keys each open batch referenced; a key is live while any set holds it. */
    private batchDistinctKeys: Map<number, Set<string>> = new Map()
    /**
     * Bumped whenever a merge outcome rewrites the memo (reconcile or a
     * failed-merge invalidation). A prefetch response issued before the
     * bump must not fill afterwards: the absence it sees may be a
     * resolution the merge just released, and filling would reinstall a
     * dead person.
     */
    private generationCounter = 0

    constructor(private hasPendingLane: (personKey: string) => boolean) {}

    get generation(): number {
        return this.generationCounter
    }

    bumpGeneration(): void {
        this.generationCounter += 1
    }

    /** How many person projections the memo currently holds. */
    get projectionCount(): number {
        return this.personState.size
    }

    /**
     * Resolves a distinct id through the batch memos, undefined on miss.
     * The update class refuses checking-grade state: a hit requires the
     * key to have been read through the leader, or a pending projection,
     * whose baseline was. Absence (a null resolution) serves both classes,
     * because resolution itself is identity-backed on either path.
     */
    lookup(teamId: number, distinctId: string, readClass: 'checking' | 'update'): InternalPerson | null | undefined {
        const distinctKey = `${teamId}:${distinctId}`
        const entry = this.resolutions.get(distinctKey)
        if (entry === undefined) {
            return undefined
        }
        if (entry.personKey === null) {
            return null
        }
        if (readClass === 'update' && entry.grade !== 'update' && !this.hasPendingLane(entry.personKey)) {
            return undefined
        }
        return this.personState.get(entry.personKey) ?? undefined
    }

    /**
     * Records a fetch result in the batch memos and returns the state
     * callers should see: an existing pending projection wins over the
     * fetched snapshot, so a fetch never rolls the batch's view back to
     * pre-update state.
     */
    record(
        teamId: number,
        distinctId: string,
        fetched: InternalPerson | null,
        batchId: number,
        options: { grade: 'checking' | 'update'; fillOnly?: boolean } = { grade: 'checking' }
    ): InternalPerson | null {
        const distinctKey = `${teamId}:${distinctId}`
        if (fetched === null) {
            // Never downgrade a live mapping: a stale prefetch response
            // can land after the batch created or resolved this person,
            // and absence must not overwrite presence.
            const existing = this.resolutions.get(distinctKey)?.personKey
            if (existing === undefined || existing === null) {
                this.recordResolution(batchId, distinctKey, null)
            }
            return existing != null ? (this.personState.get(existing) ?? null) : null
        }
        // A fill-only caller (the fire-and-forget prefetch) may deliver its
        // response arbitrarily late, so it only ever fills a hole: a
        // resolution recorded since — including a repoint by a merge — is
        // newer than the response and must stand.
        if (options.fillOnly && this.resolutions.has(distinctKey)) {
            const existing = this.resolutions.get(distinctKey)?.personKey
            return existing != null ? (this.personState.get(existing) ?? null) : null
        }
        const personKey = `${teamId}:${fetched.id}`
        this.recordResolution(batchId, distinctKey, personKey, options.grade)
        const state = this.personState
        // A projection behind a lane holds this batch's own unwritten
        // writes, which no fetch can know about — it always wins. Without
        // a lane, an awaited update-grade fetch read the leader and is
        // fresher than whatever is cached, so it replaces. A checking
        // fetch read identity, which the leader leads — and the state is
        // shared per person while grades are per key, so letting it
        // replace would degrade a baseline sibling keys still vouch for.
        // It, like a fill-only response, only ever fills absence.
        const hasPending = this.hasPendingLane(personKey)
        if (!hasPending && !options.fillOnly && options.grade === 'update') {
            state.set(personKey, fetched)
        } else if (!state.has(personKey)) {
            state.set(personKey, fetched)
        }
        return state.get(personKey) ?? fetched
    }

    /** Callers get copies: a caller stamping its result must not edit the shared memo. */
    snapshot(person: InternalPerson): InternalPerson
    snapshot(person: InternalPerson | null): InternalPerson | null
    snapshot(person: InternalPerson | null): InternalPerson | null {
        return person === null ? null : { ...person, properties: { ...person.properties } }
    }

    /** The raw resolution edge: a person key, null for known-absent, undefined on miss. */
    resolutionOf(distinctKey: string): string | null | undefined {
        return this.resolutions.get(distinctKey)?.personKey
    }

    /** A point-in-time copy of every resolution edge, safe to walk while edges change. */
    resolutionEdges(): [string, string | null][] {
        return Array.from(this.resolutions.entries(), ([key, entry]) => [key, entry.personKey])
    }

    /**
     * Grants a key the update-read grade its resolution alone does not
     * carry: the caller vouches that the person state behind it came
     * through the leader.
     */
    markUpdateGrade(distinctKey: string): void {
        const entry = this.resolutions.get(distinctKey)
        if (entry) {
            entry.grade = 'update'
        }
    }

    getProjection(personKey: string): InternalPerson | undefined {
        return this.personState.get(personKey)
    }

    hasProjection(personKey: string): boolean {
        return this.personState.has(personKey)
    }

    setProjection(personKey: string, person: InternalPerson): void {
        this.personState.set(personKey, person)
    }

    /**
     * Forgets a destroyed person entirely: state and refcounts both,
     * because the person cannot come back. The caller repoints or
     * releases the ids separately.
     */
    deletePerson(personKey: string): void {
        this.personState.delete(personKey)
        this.projectionRefCount.delete(personKey)
    }

    /** Records a resolution and this batch's reference to its distinct key. */
    recordResolution(
        batchId: number,
        distinctKey: string,
        personKey: string | null,
        grade: 'checking' | 'update' = 'checking'
    ): void {
        const previous = this.resolutions.get(distinctKey)
        if (previous?.personKey !== personKey) {
            // The edge moved, so the projection counts move with it, and
            // the key's read grade — earned on the old edge — no longer
            // describes anything. The new entry carries the caller's grade.
            if (previous?.personKey != null) {
                this.dropProjectionReference(previous.personKey)
            }
            if (personKey !== null) {
                this.projectionRefCount.set(personKey, (this.projectionRefCount.get(personKey) ?? 0) + 1)
            }
            this.resolutions.set(distinctKey, { personKey, grade })
        } else if (grade === 'update') {
            previous.grade = 'update'
        }
        let keys = this.batchDistinctKeys.get(batchId)
        if (!keys) {
            keys = new Set()
            this.batchDistinctKeys.set(batchId, keys)
        }
        keys.add(distinctKey)
    }

    /**
     * Forgets one resolution and the claim it held on its person's
     * projection. Idempotent, because a merge invalidation and the owning
     * batch's release both reach for the same key.
     */
    releaseResolution(distinctKey: string): void {
        if (!this.resolutions.has(distinctKey)) {
            return
        }
        const personKey = this.resolutions.get(distinctKey)?.personKey
        this.resolutions.delete(distinctKey)
        if (personKey != null) {
            this.dropProjectionReference(personKey)
        }
    }

    /**
     * Repoints an existing resolution at another person, moving the
     * projection refcounts with the edge. A key no batch recorded is left
     * alone: creating it here would add a mapping nothing ever releases.
     */
    repointResolution(distinctKey: string, personKey: string): void {
        const previous = this.resolutions.get(distinctKey)
        if (previous === undefined || previous.personKey === personKey) {
            return
        }
        if (previous.personKey !== null) {
            this.dropProjectionReference(previous.personKey)
        }
        this.projectionRefCount.set(personKey, (this.projectionRefCount.get(personKey) ?? 0) + 1)
        // The new person's state was never read through this key, so the
        // old grade does not carry over; the next update read re-reads.
        this.resolutions.set(distinctKey, { personKey, grade: 'checking' })
    }

    /**
     * Drops every resolution in a team and bumps the generation, for a
     * failed merge whose damage is unknowable. Projections stay: one with
     * ops still folded behind it is the batch's own read-your-write view,
     * and re-resolution repoints the ids while the projection waits for
     * its ops to write. Returns how many resolutions were dropped.
     */
    invalidateTeam(teamId: number): number {
        const teamPrefix = `${teamId}:`
        let cleared = 0
        // Collected first: releaseResolution deletes from the map under walk.
        const resolutionKeys = Array.from(this.resolutions.keys())
        for (const key of resolutionKeys) {
            if (key.startsWith(teamPrefix)) {
                // Releasing rather than deleting keeps the projection
                // refcount honest; a projection with ops still folded behind
                // it survives on the entry's claim, because dropping it would
                // let a re-fetch install committed state predating this
                // batch's own updates.
                this.releaseResolution(key)
                cleared++
            }
        }
        this.generationCounter += 1
        return cleared
    }

    private dropProjectionReference(personKey: string): void {
        const refs = (this.projectionRefCount.get(personKey) ?? 1) - 1
        if (refs > 0) {
            this.projectionRefCount.set(personKey, refs)
            return
        }
        this.projectionRefCount.delete(personKey)
        this.evictProjection(personKey)
    }

    /**
     * Frees a person's projection once nothing needs it: no lane holding
     * unwritten ops, and no live resolution naming it. Called from both
     * sides, because either can be the last to let go.
     */
    evictProjection(personKey: string): void {
        if (this.hasPendingLane(personKey) || (this.projectionRefCount.get(personKey) ?? 0) > 0) {
            return
        }
        this.personState.delete(personKey)
    }

    /**
     * Drops a batch's distinct-key references, forgetting a resolution no
     * other batch holds. The person's projection goes with it unless ops
     * are still folded behind it, which would make the eviction a lost
     * read-your-write view rather than a freed cache slot.
     */
    releaseBatch(batchId: number): void {
        const keys = this.batchDistinctKeys.get(batchId)
        this.batchDistinctKeys.delete(batchId)
        if (!keys) {
            return
        }
        for (const distinctKey of keys) {
            // Live while any still-open batch names it. A scan over the
            // open batches' key sets, rather than a maintained counter:
            // batches number in the handful, and a counter that can drift
            // out of step with the sets is a whole bug class for nothing.
            let heldElsewhere = false
            for (const other of this.batchDistinctKeys.values()) {
                if (other.has(distinctKey)) {
                    heldElsewhere = true
                    break
                }
            }
            if (!heldElsewhere) {
                this.releaseResolution(distinctKey)
            }
        }
    }
}
