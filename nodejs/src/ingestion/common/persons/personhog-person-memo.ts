import { InternalPerson } from '~/types'

/** One memo edge: the person a distinct id resolves to, null when known absent. */
interface ResolutionEntry {
    personKey: string | null
}

/**
 * An advisory cache of distinct-id resolutions and person documents,
 * shared by every open batch. The leader classifies every write, so the
 * only install rule is newer-wins and a stale view heals on the next
 * leader answer or write bounce; reads replay unsent lane ops on top.
 * Documents additionally carry provenance: the update path insists on an
 * authoritative (leader- or saga-answered) document, the way the
 * Postgres store keeps its check cache out of the update path.
 */
export class PersonhogPersonMemo {
    /**
     * Distinct-id resolution; split from person state so every id of a
     * person reads the same pending baseline.
     */
    private resolutions: Map<string, ResolutionEntry> = new Map()
    /**
     * The last document a service answered per person, keyed by
     * `${teamId}:${personId}`; never one this batch composed, so `viewOf`
     * can replay the lane's unsent ops over it without double-counting.
     */
    private baselines: Map<string, InternalPerson> = new Map()
    /**
     * Persons whose baseline lineage includes an authoritative answer.
     * A miss only costs one extra leader read, so an untagged install
     * fails safe.
     */
    private authoritativeBaselines: Set<string> = new Set()
    /**
     * How many live resolutions name each person; a counter because
     * scanning resolutions per drop would be linear.
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
     * The last service document with the lane's unsent ops replayed over
     * it. Undefined means go read one, not that the person is absent.
     */
    private viewOf(personKey: string): InternalPerson | undefined {
        const baseline = this.baselines.get(personKey)
        return baseline === undefined ? undefined : this.projectPending(personKey, baseline)
    }

    /**
     * Records a fetch result and returns the view callers should see; the
     * lane's unsent ops replay on the way out, so a fetch never rolls the
     * batch's view back to pre-update state.
     */
    record(
        teamId: number,
        distinctId: string,
        fetched: InternalPerson | null,
        batchId: number,
        options: { fillOnly?: boolean; authoritative?: boolean } = {}
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
        // A fill-only response can be arbitrarily late, so an edge recorded
        // since is newer and must stand; only the document is offered, and
        // only where the edge already names this person.
        const standingEdge = this.resolutions.get(distinctKey)?.personKey
        if (options.fillOnly && standingEdge !== undefined) {
            if (standingEdge === personKey) {
                this.offerBaseline(personKey, fetched, options)
            }
            return standingEdge !== null ? (this.viewOf(standingEdge) ?? null) : null
        }
        this.recordResolution(batchId, distinctKey, personKey)
        this.offerBaseline(personKey, fetched, options)
        return this.viewOf(personKey) ?? this.snapshot(fetched)
    }

    /**
     * The one install gate: newer-wins, because reads of one person can be
     * delivered out of order. Versions that are not both numbers fall
     * through rather than block a legitimate install.
     */
    offerBaseline(personKey: string, doc: InternalPerson, opts: { authoritative?: boolean } = {}): void {
        if (opts.authoritative) {
            // Marked even when the install below loses: a standing newer
            // document is at least as fresh as this authoritative answer.
            this.authoritativeBaselines.add(personKey)
        }
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

    /** Whether this person's baseline lineage includes an authoritative answer. */
    hasAuthoritativeBaseline(personKey: string): boolean {
        return this.authoritativeBaselines.has(personKey)
    }

    /** Callers get copies, so stamping a result cannot edit the shared memo. */
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

    /** The projected view; null where no document has been read. */
    viewOfPerson(personKey: string): InternalPerson | null {
        return this.viewOf(personKey) ?? null
    }

    /** Whether a document has been read for this person. */
    hasBaseline(personKey: string): boolean {
        return this.baselines.has(personKey)
    }

    /**
     * Forgets a destroyed person entirely, state and refcounts both; the
     * caller repoints or releases the ids separately.
     */
    deletePerson(personKey: string): void {
        this.baselines.delete(personKey)
        this.authoritativeBaselines.delete(personKey)
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
     * Forgets one resolution and its claim on the person's baseline.
     * Idempotent: a merge invalidation and the batch's release can race.
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
     * Forgets the document because something it cannot account for
     * happened; the lane keeps its unsent ops and the next reader re-reads.
     * The mark goes with it, or a later checking read could reinstall a
     * lagged document the update path would trust.
     */
    dropBaseline(personKey: string): void {
        this.baselines.delete(personKey)
        this.authoritativeBaselines.delete(personKey)
    }

    /**
     * Frees a person's baseline once no lane holds unwritten ops and no
     * live resolution names it; either side can be the last to let go.
     */
    evictBaseline(personKey: string): void {
        if (this.hasPendingLane(personKey) || (this.baselineRefCount.get(personKey) ?? 0) > 0) {
            return
        }
        this.baselines.delete(personKey)
        this.authoritativeBaselines.delete(personKey)
    }

    /**
     * Drops a batch's distinct-key references, forgetting resolutions no
     * other batch holds; a baseline with folded ops behind it survives.
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
