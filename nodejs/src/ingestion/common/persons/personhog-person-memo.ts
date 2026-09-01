import { InternalPerson } from '~/types'

/** One memo edge: the person a distinct id resolves to, null when known absent. */
interface ResolutionEntry {
    personKey: string | null
}

/**
 * An advisory cache of distinct-id resolutions and person documents,
 * shared by every open batch so a merge's purge or repoint reaches all at
 * once. Advisory means a directive, not a source of truth: the leader
 * classifies every write authoritatively, so the only install rule the
 * cache needs is newer-wins, and a stale view heals through the next
 * leader answer or a write bounce. Lanes are known through the store's
 * callbacks: a person with unwritten ops keeps its document alive, and
 * reads answer that document with those ops replayed over it.
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
     * double-counting them at a seam.
     */
    private baselines: Map<string, InternalPerson> = new Map()
    /**
     * How many live resolutions name each person; a baseline outlives its
     * own lane only while some distinct id still points at it. Maintained
     * as a counter because resolutions are numerous enough that scanning
     * them per drop would be linear where this is constant.
     */
    private baselineRefCount: Map<string, number> = new Map()
    /** Distinct keys each open batch referenced; a key is live while any set holds it. */
    private batchDistinctKeys: Map<number, Set<string>> = new Map()

    constructor(
        private hasPendingLane: (personKey: string) => boolean,
        private projectPending: (personKey: string, document: InternalPerson) => InternalPerson
    ) {}

    /** How many person baselines the memo currently holds. */
    get baselineCount(): number {
        return this.baselines.size
    }

    /** Resolves a distinct id through the batch memos, undefined on miss. */
    lookup(teamId: number, distinctId: string): InternalPerson | null | undefined {
        const entry = this.resolutions.get(`${teamId}:${distinctId}`)
        if (entry === undefined) {
            return undefined
        }
        if (entry.personKey === null) {
            return null
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
        return baseline === undefined ? undefined : this.projectPending(personKey, baseline)
    }

    /**
     * Records a fetch result and returns the view callers should see. The
     * document lands as the baseline under newer-wins; the lane's unsent
     * ops are replayed over it on the way out, so a fetch never rolls the
     * batch's view back to pre-update state.
     */
    record(
        teamId: number,
        distinctId: string,
        fetched: InternalPerson | null,
        batchId: number,
        options: { fillOnly?: boolean } = {}
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
        // A fill-only caller may deliver its response arbitrarily late, so
        // an edge recorded since — including a repoint by a merge — is
        // newer than the response and must stand; only the document is
        // offered, and only where the edge already names this person.
        const standingEdge = this.resolutions.get(distinctKey)?.personKey
        if (options.fillOnly && standingEdge !== undefined) {
            if (standingEdge === personKey) {
                this.offerBaseline(personKey, fetched)
            }
            return standingEdge !== null ? (this.viewOf(standingEdge) ?? null) : null
        }
        this.recordResolution(batchId, distinctKey, personKey)
        this.offerBaseline(personKey, fetched)
        return this.viewOf(personKey) ?? this.snapshot(fetched)
    }

    /**
     * The one gate every baseline install passes through: newer-wins.
     * Reads of one person can be delivered out of order, so a document
     * with a lower leader version is the staler read and must not replace
     * what stands; versions that are not both numbers fall through rather
     * than block a legitimate install.
     */
    offerBaseline(personKey: string, doc: InternalPerson): void {
        const existing = this.baselines.get(personKey)
        if (
            existing !== undefined &&
            typeof doc.version === 'number' &&
            typeof existing.version === 'number' &&
            doc.version < existing.version
        ) {
            return
        }
        this.baselines.set(personKey, this.snapshot(doc))
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
     * Forgets a destroyed person entirely: state and refcounts both,
     * because the person cannot come back. The caller repoints or
     * releases the ids separately.
     */
    deletePerson(personKey: string): void {
        this.baselines.delete(personKey)
        this.baselineRefCount.delete(personKey)
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
     * Drops every resolution in a team, for a failed merge whose damage is
     * unknowable; returns how many were dropped. A baseline with ops still
     * folded behind it survives, since it is the batch's read-your-write
     * view. An in-flight read can reinstall a stale edge afterwards, which
     * heals through the tombstone redirect on its next write.
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
    dropBaseline(personKey: string): void {
        this.baselines.delete(personKey)
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
        this.baselines.delete(personKey)
    }

    /**
     * Drops a batch's distinct-key references, forgetting a resolution no
     * other batch holds. The baseline goes with it unless ops are still
     * folded behind it, where eviction would lose a read-your-write view.
     */
    releaseBatch(batchId: number): void {
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
}
