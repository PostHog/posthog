import { InternalPerson } from '~/types'

type Stamped<T> = T & {
    /** Droppable once every batch with id at or below this has released. */
    staleAfter: number
}

/** A read's staleness handle; see `beginRead`. */
export interface ReadStamps {
    moved(distinctKey: string, answeredPersonKey?: string): boolean
}

/** One memo edge: the person a distinct id resolves to, null when known absent. */
interface ResolutionEntry {
    personKey: string | null
}

/**
 * Distinct-id resolution, person baselines, and the per-batch liveness
 * that decides when they can be forgotten. One instance serves every open
 * batch, so a merge's purge or repoint reaches all at once. Lanes are
 * known only through the store's callbacks: a person with unwritten ops
 * keeps its baseline alive, and reads answer that baseline with those ops
 * replayed over it.
 */
export class PersonhogPersonMemo {
    /**
     * Distinct-id resolution, shared by every open batch. Split from person
     * state so every distinct id of a person reads the same pending
     * baseline, not just the one that triggered the update.
     */
    private resolutions: Map<string, ResolutionEntry> = new Map()
    /**
     * The last document a service answered for each person, keyed by
     * `${teamId}:${personId}` and shared across batches; only ever a
     * service answer, never one this batch composed, so that `viewOf` can
     * replay the lane's unwritten ops over it without losing or
     * double-counting them at a seam. `leaderBacked` records whether the
     * document came through the leader, which the update read class
     * requires because identity lags the leader.
     */
    private baselines: Map<string, { doc: InternalPerson; leaderBacked: boolean }> = new Map()
    /**
     * How many live resolutions name each person; a baseline outlives its
     * own lane only while some distinct id still points at it. Maintained
     * as a counter because resolutions are numerous enough that scanning
     * them per drop would be linear where this is constant.
     */
    private baselineRefCount: Map<string, number> = new Map()
    /** Distinct keys each open batch referenced; a key is live while any set holds it. */
    private batchDistinctKeys: Map<number, Set<string>> = new Map()
    /**
     * How many times each distinct id's mapping has been rewritten by a
     * merge; a read stamps this before it goes out and declines to record
     * its answer on mismatch. Eviction alone cannot do this, because a
     * read already on the wire when the merge evicts returns afterwards
     * and refills the memo with the pre-merge answer.
     */
    private idVersions: Map<string, Stamped<{ version: number }>> = new Map()
    /**
     * Persons a merge has destroyed, checked against a read's own answer.
     * The merge may never have named the id the read was issued for, so a
     * sibling id of a destroyed person is the staleness an id version
     * cannot see.
     */
    private destroyedPersons: Map<string, { staleAfter: number; destroyedAtMs: number }> = new Map()
    /**
     * The least version a read may install for a person whose baseline was
     * dropped, because a read issued before the drop can be delivered into
     * the absence afterwards. The floor is what the dropper knew the
     * leader had reached, so anything below it is that stale read.
     */
    private baselineFloors: Map<string, Stamped<{ floor: number; flooredAtMs: number }>> = new Map()
    /**
     * How many times a whole team's mapping has been declared suspect by a
     * merge that failed without a verdict, whose damage is unknowable.
     * Separate from the per-id versions because that case cannot name the
     * ids it invalidates, and an in-flight read of an id the memo never
     * recorded must still decline to record.
     */
    private teamEpochs: Map<number, Stamped<{ epoch: number }>> = new Map()
    /**
     * Batches with a read handle open, and the highest batch id ever
     * opened. Each stamp entry is tagged with the highest batch open when
     * it was written, so `releaseBatch` can sweep entries whose tag is
     * below the lowest batch still open.
     */
    private openBatches: Set<number> = new Set()
    private highWaterBatch = -1

    constructor(
        private hasPendingLane: (personKey: string) => boolean,
        private projectPending: (personKey: string, document: InternalPerson) => InternalPerson,
        private writeInFlight: (personKey: string) => boolean,
        /**
         * How long a destroyed-person mark outlives the batch watermark,
         * because its consumer is a recorded merge verdict replaying in an
         * arbitrarily later batch, not a batch-bound read. Must exceed the
         * saga's op retention window (lifecycle_op_retention_hours, 24h),
         * past which no replay can arrive.
         */
        private destroyedRetentionMs: number = 25 * 60 * 60 * 1000,
        /**
         * How long a version floor outlives the batch watermark. Floors
         * also refuse reads served by a deposed leader inside its
         * detection window, a wall-clock bound of a few seconds that a
         * minute comfortably covers.
         */
        private floorRetentionMs: number = 60 * 1000
    ) {}

    /**
     * The current version of one distinct id's mapping, for a caller about
     * to read it. Compare it with `idMoved` when the read returns.
     */
    versionOf(distinctKey: string): number {
        return this.idVersions.get(distinctKey)?.version ?? 0
    }

    /** The current epoch of a team's mapping, for a caller about to read it. */
    epochOf(teamId: number): number {
        return this.teamEpochs.get(teamId)?.epoch ?? 0
    }

    /**
     * Records that a merge destroyed this person and drops any standing
     * baseline with it. The mark refuses every future install, so a
     * leftover document would serve the dead person for the rest of the
     * batch with nothing able to replace it.
     */
    markDestroyed(personKey: string): void {
        this.destroyedPersons.set(personKey, {
            staleAfter: this.stampHorizon(this.destroyedPersons.get(personKey)?.staleAfter),
            destroyedAtMs: Date.now(),
        })
        const held = this.baselines.get(personKey)
        if (held !== undefined) {
            this.dropBaseline(personKey, typeof held.doc.version === 'number' ? held.doc.version : undefined)
        }
    }

    /**
     * How many destroyed-person marks are held. The marks outlive the
     * batch watermark by the replay retention, so their population is the
     * one stamp store whose size tracks merge volume rather than batch
     * churn; exposed for the gauge that watches it.
     */
    destroyedCount(): number {
        return this.destroyedPersons.size
    }

    /** Whether a merge has destroyed this person. */
    isDestroyed(personKey: string): boolean {
        return this.destroyedPersons.has(personKey)
    }

    /**
     * The stamps a read takes before it goes out: take the handle
     * synchronously before the first await, then ask `moved` on return,
     * passing the person the read answered with when it has one. `moved`
     * is true when anything has superseded the read (a merge that spoke
     * for the id, a failed merge that left the team suspect, or one that
     * destroyed the answered person), and a key the handle was not opened
     * for always reads as moved.
     */
    beginRead(teamId: number, batchId: number, distinctKeys: string[]): ReadStamps {
        // The handle is what makes a batch visible as open: liveness must
        // begin before the first await, not at the first recorded result,
        // or a batch whose first read is still on the wire looks closed and
        // its stamps get swept from under it.
        this.openBatches.add(batchId)
        this.highWaterBatch = Math.max(this.highWaterBatch, batchId)
        const stamps = new Map(
            distinctKeys.map((key) => [key, { version: this.versionOf(key), epoch: this.epochOf(teamId) }])
        )
        return {
            moved: (distinctKey: string, answeredPersonKey?: string): boolean => {
                const issued = stamps.get(distinctKey)
                if (issued === undefined) {
                    return true
                }
                if (this.versionOf(distinctKey) !== issued.version || this.epochOf(teamId) !== issued.epoch) {
                    return true
                }
                return answeredPersonKey !== undefined && this.isDestroyed(answeredPersonKey)
            },
        }
    }

    /**
     * Records that a merge rewrote this id's mapping, so any read of it still
     * in flight declines to record what it finds.
     */
    bumpId(distinctKey: string): void {
        this.idVersions.set(distinctKey, {
            version: this.versionOf(distinctKey) + 1,
            staleAfter: this.stampHorizon(this.idVersions.get(distinctKey)?.staleAfter),
        })
    }

    /**
     * The highest batch a stamp written now could matter to: a read holding
     * the pre-bump value belongs to a batch open at this moment. Re-stamps
     * keep the older horizon when it is higher, so a tag never moves down.
     */
    private stampHorizon(existing?: number): number {
        const horizon = this.openBatches.size > 0 ? this.highWaterBatch : -1
        return Math.max(existing ?? -1, horizon)
    }

    /** How many person baselines the memo currently holds. */
    get baselineCount(): number {
        return this.baselines.size
    }

    /**
     * Resolves a distinct id through the batch memos, undefined on miss.
     * The update class refuses state identity answered, so a hit needs a
     * leader-backed baseline or a pending lane; a null resolution is
     * identity-backed either way, so it serves both classes.
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
        // A pending lane serves the update class regardless of provenance:
        // the view carries the batch's own unsent ops, which no re-read
        // could improve on.
        if (
            readClass === 'update' &&
            this.baselines.get(entry.personKey)?.leaderBacked !== true &&
            !this.hasPendingLane(entry.personKey)
        ) {
            return undefined
        }
        return this.viewOf(entry.personKey)
    }

    /**
     * What this batch should see for a person: the last document a service
     * answered, with the ops the person's lane has not sent replayed over
     * it. Undefined where no document has been read, which is an instruction
     * to go and read one rather than a statement that the person is absent.
     */
    private viewOf(personKey: string): InternalPerson | undefined {
        const baseline = this.baselines.get(personKey)
        return baseline === undefined ? undefined : this.projectPending(personKey, baseline.doc)
    }

    /**
     * Records a fetch result and returns the view callers should see. The
     * document lands as the baseline under the rules below; the lane's
     * unsent ops are replayed over it on the way out, so a fetch never rolls
     * the batch's view back to pre-update state.
     */
    record(
        teamId: number,
        distinctId: string,
        fetched: InternalPerson | null,
        batchId: number,
        options: { readClass: 'checking' | 'update'; fillOnly?: boolean } = { readClass: 'checking' }
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
            return existing != null ? (this.viewOf(existing) ?? null) : null
        }
        const personKey = `${teamId}:${fetched.id}`
        // A destroyed person is never recorded, whichever path offered it.
        // This catches callers that hold an answer rather than a read (a
        // replayed merge verdict whose survivor a later merge destroyed)
        // and hands the answer back exactly as a declined read does.
        if (this.destroyedPersons.has(personKey)) {
            return this.snapshot(fetched)
        }
        // The read class names the service that answered: update reads
        // carry the leader's document, checking reads identity's. Fill-only
        // caps what the install may do, not who produced the document.
        const provenance =
            options.readClass === 'update' ? (options.fillOnly ? 'leader-fill' : 'leader-read') : 'identity-read'
        // A fill-only caller may deliver its response arbitrarily late, so an
        // edge recorded since — including a repoint by a merge — is newer
        // than the response and must stand.
        const standingEdge = this.resolutions.get(distinctKey)?.personKey
        if (options.fillOnly && standingEdge !== undefined) {
            // A standing edge already owns this person's baseline, so
            // supplying a document it lacks costs nothing and creates
            // nothing. Whether the batch that asked is still open does not
            // matter, because no reference is claimed either way.
            if (standingEdge === personKey) {
                this.offerBaseline(personKey, fetched, provenance)
            }
            return standingEdge !== null ? (this.viewOf(standingEdge) ?? null) : null
        }
        this.recordResolution(batchId, distinctKey, personKey)
        this.offerBaseline(personKey, fetched, provenance)
        return this.viewOf(personKey) ?? this.snapshot(fetched)
    }

    /**
     * The one gate every baseline install passes through, with policy set
     * by provenance: 'leader-read' and 'own-write' may replace a baseline
     * under the version guard, while 'identity-read' (identity lags the
     * leader) and 'leader-fill' (delivered arbitrarily late) only fill
     * absence. Reads are refused while one of this person's own writes is
     * on the wire, because the answer cannot be classified pre- or
     * post-apply; 'own-write' is ordered against the write by construction
     * but stays version-guarded, because the lane and the direct diff
     * update are independent writers whose answers can be delivered
     * inverted.
     */
    offerBaseline(
        personKey: string,
        doc: InternalPerson,
        provenance: 'leader-read' | 'identity-read' | 'leader-fill' | 'own-write'
    ): void {
        // No provenance outranks destruction. A destroyed person's row id is
        // never reused, so this can only refuse documents that genuinely
        // describe a person that no longer exists — installing one would
        // resurrect it as the batch's live answer.
        if (this.destroyedPersons.has(personKey)) {
            return
        }
        switch (provenance) {
            case 'leader-read':
                if (
                    this.refusesDocuments(personKey) ||
                    this.belowFloor(personKey, doc) ||
                    !this.mayReplaceBaseline(personKey, doc)
                ) {
                    return
                }
                break
            case 'identity-read':
            case 'leader-fill':
                if (
                    this.refusesDocuments(personKey) ||
                    this.belowFloor(personKey, doc) ||
                    this.baselines.has(personKey)
                ) {
                    return
                }
                break
            case 'own-write':
                // The floor applies here too: a late answer from one writer
                // can land after the other's drop, which the version guard
                // cannot see when the baseline is absent.
                if (this.belowFloor(personKey, doc) || !this.mayReplaceBaseline(personKey, doc)) {
                    return
                }
                break
        }
        // Identity is the one source that lags the leader; every other
        // provenance is the leader's answer, directly or through the
        // merge's fold. The flag only moves upward while the baseline
        // stands, because an identity read never replaces an existing one.
        this.baselines.set(personKey, { doc: this.snapshot(doc), leaderBacked: provenance !== 'identity-read' })
        this.clearFloorIfCovered(personKey, doc)
    }

    /** Whether a read's document predates what the leader was known to hold at drop time. */
    private belowFloor(personKey: string, doc: InternalPerson): boolean {
        const floor = this.baselineFloors.get(personKey)
        if (floor === undefined) {
            return false
        }
        return typeof doc.version === 'number' && doc.version < floor.floor
    }

    private clearFloorIfCovered(personKey: string, doc: InternalPerson): void {
        const floor = this.baselineFloors.get(personKey)
        if (floor === undefined) {
            return
        }
        if (typeof doc.version !== 'number' || doc.version >= floor.floor) {
            this.baselineFloors.delete(personKey)
        }
    }

    /**
     * Whether a document read from a service can be trusted as a baseline
     * right now. While one of this person's ops is on the wire it cannot,
     * because the leader may or may not have applied the op when the read
     * was served, and replaying the lane over the wrong answer loses the
     * op or counts it twice.
     */
    private refusesDocuments(personKey: string): boolean {
        return this.writeInFlight(personKey)
    }

    /**
     * Callers get copies: a caller stamping its result must not edit the
     * shared memo. Reads that go through `viewOf` are already fresh objects,
     * so they do not need copying again.
     */
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
     * What the batch sees for this person: the baseline with the lane's
     * unsent ops replayed over it. Null where no document has been read.
     */
    viewOfPerson(personKey: string): InternalPerson | null {
        return this.viewOf(personKey) ?? null
    }

    /** Whether a document has been read for this person. */
    hasBaseline(personKey: string): boolean {
        return this.baselines.has(personKey)
    }

    /**
     * Whether a fetched document may replace the baseline. Reads of one
     * person can be delivered out of order, so a document with a lower
     * leader version is the staler read and must not replace what stands;
     * versions that are not both numbers fall through rather than block a
     * legitimate install.
     */
    private mayReplaceBaseline(personKey: string, fetched: InternalPerson): boolean {
        const existing = this.baselines.get(personKey)?.doc
        if (existing === undefined) {
            return true
        }
        if (typeof fetched.version !== 'number' || typeof existing.version !== 'number') {
            return true
        }
        return fetched.version >= existing.version
    }

    /**
     * Forgets a destroyed person entirely: state and refcounts both,
     * because the person cannot come back. The caller repoints or
     * releases the ids separately.
     */
    deletePerson(personKey: string): void {
        this.baselines.delete(personKey)
        this.baselineRefCount.delete(personKey)
        this.baselineFloors.delete(personKey)
    }

    /** Records a resolution and this batch's reference to its distinct key. */
    recordResolution(batchId: number, distinctKey: string, personKey: string | null): void {
        const previous = this.resolutions.get(distinctKey)
        if (previous?.personKey !== personKey) {
            // The edge moved, so the baseline counts move with it.
            if (previous?.personKey != null) {
                this.dropBaselineReference(previous.personKey)
            }
            if (personKey !== null) {
                this.baselineRefCount.set(personKey, (this.baselineRefCount.get(personKey) ?? 0) + 1)
            }
            this.resolutions.set(distinctKey, { personKey })
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
     * baseline. Idempotent, because a merge invalidation and the owning
     * batch's release both reach for the same key.
     */
    releaseResolution(distinctKey: string): void {
        if (!this.resolutions.has(distinctKey)) {
            return
        }
        const personKey = this.resolutions.get(distinctKey)?.personKey
        this.resolutions.delete(distinctKey)
        if (personKey != null) {
            this.dropBaselineReference(personKey)
        }
    }

    /**
     * Repoints an existing resolution at another person, moving the
     * baseline refcounts with the edge. A key no batch recorded is left
     * alone: creating it here would add a mapping nothing ever releases.
     */
    repointResolution(distinctKey: string, personKey: string): void {
        const previous = this.resolutions.get(distinctKey)
        if (previous === undefined || previous.personKey === personKey) {
            return
        }
        if (previous.personKey !== null) {
            this.dropBaselineReference(previous.personKey)
        }
        this.baselineRefCount.set(personKey, (this.baselineRefCount.get(personKey) ?? 0) + 1)
        this.resolutions.set(distinctKey, { personKey })
    }

    /**
     * Drops every resolution in a team and bumps the generation, for a
     * failed merge whose damage is unknowable; returns how many were
     * dropped. A baseline with ops still folded behind it survives, since
     * it is the batch's read-your-write view.
     */
    invalidateTeam(teamId: number): number {
        const teamPrefix = `${teamId}:`
        let cleared = 0
        // Collected first: releaseResolution deletes from the map under walk.
        const resolutionKeys = Array.from(this.resolutions.keys())
        for (const key of resolutionKeys) {
            if (key.startsWith(teamPrefix)) {
                // Releasing rather than deleting keeps the baseline
                // refcount honest and lets a baseline with folded ops
                // survive, so a re-fetch cannot install committed state
                // predating this batch's own updates.
                this.releaseResolution(key)
                cleared++
            }
        }
        this.teamEpochs.set(teamId, {
            epoch: this.epochOf(teamId) + 1,
            staleAfter: this.stampHorizon(this.teamEpochs.get(teamId)?.staleAfter),
        })
        return cleared
    }

    private dropBaselineReference(personKey: string): void {
        const refs = (this.baselineRefCount.get(personKey) ?? 1) - 1
        if (refs > 0) {
            this.baselineRefCount.set(personKey, refs)
            return
        }
        this.baselineRefCount.delete(personKey)
        this.evictBaseline(personKey)
    }

    /**
     * Forgets the document this batch was answering reads from, because
     * something it cannot account for has happened, such as a redirect
     * landing another lane's ops on this person. Only the document goes:
     * the lane keeps its unsent ops, and the next reader is sent to the
     * service rather than to a guess.
     */
    dropBaseline(personKey: string, floorVersion?: number): void {
        this.baselines.delete(personKey)
        if (typeof floorVersion === 'number') {
            const existing = this.baselineFloors.get(personKey)
            if (existing === undefined || floorVersion > existing.floor) {
                this.baselineFloors.set(personKey, {
                    floor: floorVersion,
                    flooredAtMs: Date.now(),
                    staleAfter: this.stampHorizon(existing?.staleAfter),
                })
            }
        }
    }

    /**
     * Whether a document sits below this person's standing floor. The
     * install gates already refuse such a document; the read path must
     * also not hand one to its caller, where it could suppress a genuine
     * change as no-change.
     */
    refusesBelowFloor(personKey: string, doc: InternalPerson): boolean {
        return this.belowFloor(personKey, doc)
    }

    /**
     * Drops a baseline because writes it cannot know about reached this
     * person, unless the standing document is already at or past the
     * written version and so contains them. The floor is the highest
     * version this call can prove the leader reached, which admits an
     * equal-version delivery that raced the writes, because flooring one
     * higher would wedge re-reads whenever the standing document already
     * contained the writes.
     */
    dropBaselineBehindWrites(personKey: string, writtenVersion: number | undefined): void {
        const standing = this.baselines.get(personKey)?.doc.version
        if (typeof standing === 'number' && typeof writtenVersion === 'number' && standing >= writtenVersion) {
            return
        }
        const anchors = [standing, writtenVersion].filter((v): v is number => typeof v === 'number')
        this.dropBaseline(personKey, anchors.length > 0 ? Math.max(...anchors) : undefined)
    }

    /**
     * Advances an existing floor by one for a null write answer landing on
     * an absence: the leader applied a write, so it moved past the old
     * floor, which is the only anchor available. With no existing floor
     * there is nothing to anchor on, and the person is left alone.
     */
    raiseFloorPastAppliedWrite(personKey: string): void {
        const existing = this.baselineFloors.get(personKey)
        if (existing === undefined) {
            return
        }
        this.baselineFloors.set(personKey, {
            floor: existing.floor + 1,
            flooredAtMs: Date.now(),
            staleAfter: this.stampHorizon(existing.staleAfter),
        })
    }

    /**
     * Frees a person's baseline once nothing needs it: no lane holding
     * unwritten ops, and no live resolution naming it. Called from both
     * sides, because either can be the last to let go.
     */
    evictBaseline(personKey: string): void {
        if (this.hasPendingLane(personKey) || (this.baselineRefCount.get(personKey) ?? 0) > 0) {
            return
        }
        // The eviction leaves an absence a late-delivered read could fill
        // with older state, so floor at the held version, which the leader
        // has genuinely reached; equal-version readmission stays allowed.
        const evicted = this.baselines.get(personKey)
        this.dropBaseline(personKey, typeof evicted?.doc.version === 'number' ? evicted.doc.version : undefined)
    }

    /**
     * Drops a batch's distinct-key references, forgetting a resolution no
     * other batch holds. The baseline goes with it unless ops are still
     * folded behind it, where eviction would lose a read-your-write view.
     */
    releaseBatch(batchId: number): void {
        this.openBatches.delete(batchId)
        this.sweepStamps()
        const keys = this.batchDistinctKeys.get(batchId)
        this.batchDistinctKeys.delete(batchId)
        if (!keys) {
            return
        }
        for (const distinctKey of keys) {
            // Live while any still-open batch names it; a scan rather than
            // a maintained counter, because batches number in the handful
            // and a counter can drift out of step with the sets.
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

    /**
     * Drops every stamp no in-flight read can still be holding: a stamp
     * matters only to reads from batches open at its bump, all of which
     * have released once the entry's horizon is below the lowest open
     * batch. A read racing the sweep sees version zero, mismatches, and
     * declines, which is the safe direction at the cost of one re-read.
     */
    private sweepStamps(): void {
        let lowestOpen = Infinity
        for (const open of this.openBatches) {
            lowestOpen = Math.min(lowestOpen, open)
        }
        for (const [key, entry] of this.idVersions) {
            if (entry.staleAfter < lowestOpen) {
                this.idVersions.delete(key)
            }
        }
        // Destroyed marks wait out the verdict-replay window as well as
        // the watermark: their consumer is a replayed merge verdict, not a
        // batch-bound read, and it can arrive as long as the saga retains
        // the recorded op.
        const replayHorizonMs = Date.now() - this.destroyedRetentionMs
        for (const [key, entry] of this.destroyedPersons) {
            if (entry.staleAfter < lowestOpen && entry.destroyedAtMs < replayHorizonMs) {
                this.destroyedPersons.delete(key)
            }
        }
        for (const [key, entry] of this.teamEpochs) {
            if (entry.staleAfter < lowestOpen) {
                this.teamEpochs.delete(key)
            }
        }
        // Floors wait out a short wall clock as well as the watermark:
        // beyond the batch-bound reads they were built for, they now also
        // refuse fresh reads served inside a deposed leader's detection
        // window, and that window is bounded by time, not batch liveness.
        const floorHorizonMs = Date.now() - this.floorRetentionMs
        for (const [key, entry] of this.baselineFloors) {
            if (entry.staleAfter < lowestOpen && entry.flooredAtMs < floorHorizonMs) {
                this.baselineFloors.delete(key)
            }
        }
    }
}
