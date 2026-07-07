/**
 * Bundle store contract — the content layer for an AgentRevision.
 *
 * While `state = draft`, the bundle is a mutable directory. Every `writeFile`
 * overwrites in-place. On `promote`, the bundle is frozen (zipped or marked
 * read-only) and a sha256 stamped on the row.
 *
 * Two implementations:
 *   - S3BundleStore (prod): each revision is a key prefix.
 *   - MemoryBundleStore (tests + local dev): in-process Map.
 */

export interface BundleStore {
    list(revisionId: string, prefix?: string): Promise<BundleEntry[]>
    read(revisionId: string, path: string): Promise<Buffer>
    readText(revisionId: string, path: string): Promise<string>
    write(revisionId: string, path: string, content: Buffer | string): Promise<void>
    delete(revisionId: string, path: string): Promise<void>
    exists(revisionId: string, path: string): Promise<boolean>
    /** Whether a `.frozen` marker has been written for this revision. The
     *  authoritative cross-process signal for "this bundle is immutable" —
     *  more reliable than `agent_revision.state` since Django stamps state
     *  *after* the janitor returns, leaving a brief window where state is
     *  still `draft` but the bundle is already frozen on disk. */
    isFrozen(revisionId: string): Promise<boolean>
    /**
     * Freeze a draft bundle. Returns sha256 of the frozen contents.
     *
     * `precomputedEntries`: if the caller already has the result of a recent
     * `list()` call (e.g. the freeze handler that called `readTypedBundle`
     * a moment ago), pass it in. Saves a round-trip's worth of N+1 HEADs
     * on every freeze of a multi-file bundle.
     */
    freeze(revisionId: string, precomputedEntries?: BundleEntry[]): Promise<string>
    /** Copy one file between revisions (used by cross-agent reuse). */
    copy(srcRev: string, srcPath: string, dstRev: string, dstPath: string): Promise<void>
}

export interface BundleEntry {
    path: string
    size: number
    sha256: string
}
