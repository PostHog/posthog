import { readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'

import { cleanUp, cssTargets, jsTarget, type CleanupTarget } from './cleanup'
import { contentHash } from './container'
import { discover, isDsymBundle, isIgnored, listFiles, type Artifact, type Root } from './discover'
import { GitError, gitInfo, type GitInfo } from './git'
import {
    dropDuplicateChunks,
    injectEventMode,
    injectSymbolSetMode,
    preparePair,
    randomChunkId,
    releaseRequested,
    resolveJsRelease,
    StagedFiles,
    type InjectAction,
    type PreparedPair,
} from './js-flow'
import { decodeUtf8 } from './json'
import {
    cloneMetadata,
    hermesMapBytes,
    hermesSkipReason,
    hermesUpload,
    isHermesBundlePath,
    readHermesMap,
    type HermesMap,
    type HermesMapSkip,
} from './kinds/hermes'
import {
    loadMapContent,
    readPair,
    serializeMapContent,
    SourcePair,
    type MapIds,
    type ReleaseMode,
    type Skip,
} from './kinds/js'
import { proguardContainer } from './kinds/proguard'
import {
    dedupeNativeFiles,
    dsymSlices,
    dsymUpload,
    mergePreferDsym,
    nativeCandidates,
    nativeUpload,
    type NativeFile,
    type NativeProblem,
} from './native/package'
import { sourceStep } from './native/sources'
import { plistRelease } from './plist'
import { fetchOrCreateRelease, resolveRelease, type Release, type ReleaseFields } from './release'
import { Scratch, sizeOnly } from './scratch'
import {
    SymbolSetClient,
    uploadBytes,
    type KeepData,
    type StoredData,
    type SymbolSetUpload,
    type UploadStatus,
} from './upload'

export interface ErrorTrackingOptions {
    kind?: ArtifactKind
    mapId?: string
    release: ReleaseFields
    infoPlist?: string
    releaseMode: ReleaseMode
    publicPathPrefix?: string
    force: boolean
    skipOnConflict: boolean
    // Undefined uses posthog-cli's default for each artifact type.
    batchSize?: number
    concurrency: number
    deleteAfter: boolean
    includeSource: boolean
    dryRun: boolean
}

export interface ReleaseReport {
    name: string
    version: string
    id: string | null
}

export interface SymbolSetReport {
    path: string
    kind: ArtifactKind
    chunkId: string
    contentHash: string
    size: number
    status: UploadStatus | 'planned'
}

export interface InjectedReport {
    path: string
    map: string
    chunkId: string
    action: InjectAction
}

export interface Selection {
    artifacts: Artifact[]
    roots: Root[]
    cwd: string
}

export async function select(ctx: Context, paths: string[], options: ErrorTrackingOptions): Promise<Selection> {
    let roots: Root[]
    let cwd: string
    if (paths.length > 0) {
        roots = paths.map((path) => ({ path, kind: options.kind, mapId: options.mapId }))
        cwd = ctx.runtime.cwd()
    } else {
        const loaded = await ctx.config()
        const sources = loaded?.config.errorTracking?.sources ?? []
        if (!loaded || sources.length === 0) {
            throw new HogError(
                'no_paths',
                'Pass the files or folders to process, or list them under errorTracking.sources in posthog.json.',
                'Run `hog config schema` to see the posthog.json format.',
                EXIT_USAGE
            )
        }
        roots = sources.map((source) => ({ ...source, kind: options.kind ?? source.kind }))
        cwd = loaded.root
    }
    return { artifacts: discover(roots, cwd, { publicPathPrefix: options.publicPathPrefix }), roots, cwd }
}

// The flags first, then --info-plist, then posthog.json.
export async function releaseFields(ctx: Context, options: ErrorTrackingOptions): Promise<ReleaseFields> {
    const configured = (await ctx.config())?.config.errorTracking?.release
    const plist = options.infoPlist ? plistRelease(resolve(ctx.runtime.cwd(), options.infoPlist), ctx.runtime.env) : {}
    return {
        name: options.release.name ?? plist.name ?? configured?.name,
        version: options.release.version ?? plist.version ?? configured?.version,
        build: options.release.build ?? plist.build,
    }
}

class Releases {
    private readonly cache = new Map<string, Promise<Release>>()

    constructor(private readonly client: () => Promise<SymbolSetClient>) {}

    get(name: string, version: string, git: GitInfo | undefined): Promise<Release> {
        const key = `${name}\u0000${version}`
        if (!this.cache.has(key)) {
            this.cache.set(
                key,
                this.client().then((client) => fetchOrCreateRelease(client, name, version, git ? { git } : {}))
            )
        }
        return this.cache.get(key)!
    }
}

// One API client and one release cache per command, created on first use so dry runs and
// `inject` without a release never read credentials.
export class Session {
    private client: Promise<SymbolSetClient> | undefined
    readonly releases = new Releases(() => this.getClient())

    constructor(private readonly ctx: Context) {}

    getClient(): Promise<SymbolSetClient> {
        this.client ??= this.ctx
            .session()
            .then(
                (session) =>
                    new SymbolSetClient(this.ctx.runtime, session, () =>
                        this.ctx.telemetry.capture('error_tracking_cli_sourcemaps_upload_endpoint_fallback')
                    )
            )
        return this.client
    }
}

const isBundle = (artifact: Artifact): boolean =>
    artifact.kind === 'js' || (artifact.kind === 'hermes' && isHermesBundlePath(artifact.path))

interface OwnedPair {
    pair: SourcePair
    artifact: Artifact
}

// A step that needs one fact about the pairs, such as whether any of them lacks a release, reads
// them before the step that does the work, and it usually stops at the first pair. Remembering
// the last pair read keeps that from parsing the same map twice.
class PairReader {
    private last: { path: string; pair: SourcePair | undefined; skipped: Skip[] } | undefined

    constructor(private readonly publicPathPrefix: string | undefined) {}

    read(path: string, skipped: Skip[]): SourcePair | undefined {
        if (this.last?.path !== path) {
            const found: Skip[] = []
            this.last = { path, pair: readPair(path, this.publicPathPrefix, found), skipped: found }
        }
        skipped.push(...this.last.skipped)
        return this.last.pair
    }

    // For the step that changes the pair, so that no later read sees the changes.
    take(path: string, skipped: Skip[]): SourcePair | undefined {
        const pair = this.read(path, skipped)
        this.last = undefined
        return pair
    }
}

// JavaScriptCore lets its heap grow with the memory of the machine before it collects, and a pair
// leaves behind several times its size in parsed JSON and mapping tokens. A collection after a
// fixed amount of bundle text keeps the memory hog holds near what the largest pair needs.
const COLLECT_AFTER_SOURCE_CHARS = 16 * 1024 * 1024
// Transforming a bundle takes many times its size, so a large one starts from a heap without
// the garbage of the pairs before it.
const LARGE_SOURCE_CHARS = 4 * 1024 * 1024
let uncollectedSourceChars = 0

function collect(): void {
    uncollectedSourceChars = 0
    Bun.gc(true)
}

const isLarge = (pair: SourcePair): boolean => pair.source.length >= LARGE_SOURCE_CHARS

function pairRead(pair: SourcePair): void {
    if (isLarge(pair) && uncollectedSourceChars > 0) {
        collect()
    }
}

function pairDone(pair: SourcePair): void {
    uncollectedSourceChars += pair.source.length
    if (uncollectedSourceChars >= COLLECT_AFTER_SOURCE_CHARS || isLarge(pair)) {
        collect()
    }
}

function* readPairs(
    selection: Selection,
    reader: PairReader,
    skipped: Skip[],
    read: 'read' | 'take' = 'take'
): Generator<OwnedPair> {
    const seen = new Set<string>()
    for (const artifact of selection.artifacts.filter(isBundle)) {
        const pair = reader[read](artifact.path, skipped)
        if (
            pair &&
            isIgnored(
                artifact.root,
                realpathSync(resolve(selection.cwd, artifact.root.path)),
                realpathSync(pair.mapPath)
            )
        ) {
            skipped.push({
                path: artifact.display,
                reason: `its sourcemap matches an ignore pattern in posthog.json`,
                intended: true,
            })
            continue
        }
        if (pair && !seen.has(pair.sourcePath)) {
            seen.add(pair.sourcePath)
            pairRead(pair)
            yield { pair, artifact }
            pairDone(pair)
        }
    }
}

function some<T>(items: Iterable<T>, matches: (item: T) => boolean): boolean {
    for (const item of items) {
        if (matches(item)) {
            return true
        }
    }
    return false
}

const isUploadable = (pair: SourcePair): boolean => pair.chunkId() !== null || pair.debugId() !== null

interface JsEntry {
    artifact: Artifact
    uploadable: boolean
    // Read before the upload stamps its own release on the pair.
    withoutRelease: boolean
    target: CleanupTarget | undefined
    prepared: PreparedPair
}

interface JsEntryOptions {
    releaseMode: ReleaseMode
    deleteAfter: boolean
    keep: (data: Uint8Array) => StoredData
    releaseId?: string
}

function jsEntry({ pair, artifact }: OwnedPair, options: JsEntryOptions): JsEntry {
    const uploadable = isUploadable(pair)
    const withoutRelease = pair.map.releaseId === null
    // The fingerprint covers the map as it is on disk, so it comes before the release is stamped.
    const target = uploadable && options.deleteAfter ? jsTarget(pair) : undefined

    if (uploadable && options.releaseId !== undefined) {
        pair.map.releaseId = options.releaseId
    }
    return {
        artifact,
        uploadable,
        withoutRelease,
        target,
        prepared: preparePair(pair, options.releaseMode, options.keep),
    }
}

// The injected pairs, kept on disk for the upload step of `process`. The files in the build can't
// stand in for them: two bundles can share one map, and then the file holds only the last one.
class PairSnapshot {
    private readonly stored: {
        sourcePath: string
        mapPath: string
        source: StoredData
        map: StoredData
        artifact: Artifact
    }[] = []

    constructor(private readonly scratch: Scratch) {}

    add({ pair, artifact }: OwnedPair): void {
        this.stored.push({
            sourcePath: pair.sourcePath,
            mapPath: pair.mapPath,
            source: this.scratch.write(Buffer.from(pair.source, 'utf8')),
            map: this.scratch.write(Buffer.from(serializeMapContent(pair.map), 'utf8')),
            artifact,
        })
    }

    *pairs(): Generator<OwnedPair> {
        for (const { sourcePath, mapPath, source, map, artifact } of this.stored) {
            const pair = new SourcePair(
                sourcePath,
                decodeUtf8(source.read()),
                mapPath,
                loadMapContent(decodeUtf8(map.read()))
            )
            pairRead(pair)
            yield { pair, artifact }
            pairDone(pair)
        }
    }
}

// In symbol-set mode, an upload that found no release yet resolves one after every file is
// written, and stamps it on the maps it uploads. Only then does an upload change a pair.
const uploadStampsRelease = (options: ErrorTrackingOptions, release: ReleaseReport | null): boolean =>
    options.releaseMode === 'symbol-set' && release === null && !options.dryRun

// What the inject step of `process` passes to its upload step in place of the pairs. The entries
// are final when the upload can't change a pair. Otherwise the upload reads the pairs back.
type Handoff = { entries: JsEntry[]; failure?: { error: unknown } } | { snapshot: PairSnapshot }

export interface InjectReport {
    release: ReleaseReport | null
    injected: InjectedReport[]
    skipped: Skip[]
    warnings: string[]
}

export async function inject(ctx: Context, selection: Selection, options: ErrorTrackingOptions): Promise<InjectReport> {
    return (await injectPairs(ctx, selection, options, new Session(ctx))).report
}

async function injectPairs(
    ctx: Context,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session,
    forProcess?: { preset: Release | undefined; scratch: Scratch }
): Promise<{ report: InjectReport; handoff: Handoff | undefined }> {
    const skipped: Skip[] = []
    const warnings: string[] = []
    const reader = new PairReader(options.publicPathPrefix)
    const peek = (): Generator<OwnedPair> => readPairs(selection, reader, [], 'read')
    if (!some(peek(), () => true)) {
        throw new HogError(
            'no_bundles',
            'hog found no JavaScript or Hermes bundles with sourcemaps to inject in those paths.',
            'Check the paths, or pass --public-path-prefix if your sourceMappingURL comments are absolute URLs.'
        )
    }
    const fields = await releaseFields(ctx, options)
    let release = forProcess?.preset
    let reported: ReleaseReport | null = release
        ? { name: release.project, version: release.version, id: release.id }
        : null
    if (!release) {
        // Hermes bundles never carry a release in event mode: the app's own metadata names it.
        const needed =
            options.releaseMode === 'event'
                ? some(peek(), ({ artifact }) => artifact.kind !== 'hermes')
                : releaseRequested(fields) || some(peek(), ({ pair }) => pair.map.releaseId === null)
        const resolved = needed ? resolveJsRelease(fields, ctx.runtime.env, selection.cwd, warnings) : undefined
        if (resolved) {
            reported = { name: resolved.name, version: resolved.version, id: null }
            if (options.dryRun) {
                warnings.push(DRY_RUN_RELEASE_WARNING)
            } else {
                release = await session.releases.get(resolved.name, resolved.version, resolved.git)
                reported.id = release.id
            }
        } else if (options.releaseMode === 'event' && needed) {
            warnings.push(
                'No release could be resolved, so hog injected chunk IDs only and events will carry no release.'
            )
        }
    }
    const releaseId = release?.id ?? null

    let handoff: Handoff | undefined
    if (forProcess) {
        handoff = uploadStampsRelease(options, reported)
            ? { snapshot: new PairSnapshot(forProcess.scratch) }
            : { entries: [] }
    }
    const entryOptions: JsEntryOptions | undefined = forProcess && {
        releaseMode: options.releaseMode,
        deleteAfter: options.deleteAfter,
        keep: options.dryRun ? sizeOnly : forProcess.scratch.write,
    }
    const pass = (owned: OwnedPair): void => {
        if (!handoff || !entryOptions || owned.artifact.kind !== 'js') {
            return
        }
        // Packaging a pair for upload transforms it once more, so the garbage of the injection goes first.
        if (isLarge(owned.pair)) {
            collect()
        }
        if ('snapshot' in handoff) {
            handoff.snapshot.add(owned)
        } else if (!handoff.failure) {
            // The upload step reports a pair it can't package, after the files are written.
            try {
                handoff.entries.push(jsEntry(owned, entryOptions))
            } catch (error) {
                handoff.failure = { error }
            }
        }
    }

    const newId = randomChunkId(ctx.runtime.now)
    // In event mode, the warnings for JavaScript bundles come before the ones for Hermes bundles.
    const hermesWarnings: string[] = []
    const injected: InjectedReport[] = []
    const cwd = realpathSync(selection.cwd)
    const files = new StagedFiles()
    // The first error a person sees stays the same whatever the order of the pairs on disk: a
    // JavaScript pair that can't be transformed, then a Hermes pair in event mode, then a file
    // that can't be staged.
    let hermesFailure: { error: unknown } | undefined
    let stagingFailure: { error: unknown } | undefined
    let withoutRelease = false
    try {
        for (const owned of readPairs(selection, reader, skipped)) {
            const { pair, artifact } = owned
            let outcome
            if (options.releaseMode === 'symbol-set') {
                outcome = injectSymbolSetMode(pair, releaseId, newId)
            } else if (artifact.kind !== 'hermes') {
                outcome = injectEventMode(pair, releaseId, warnings)
            } else if (hermesFailure) {
                continue
            } else {
                try {
                    outcome = injectEventMode(pair, null, hermesWarnings)
                } catch (error) {
                    hermesFailure = { error }
                    continue
                }
            }
            withoutRelease ||= pair.map.releaseId === null
            injected.push({
                path: artifact.display,
                map: relative(cwd, pair.mapPath),
                chunkId: outcome.chunkId,
                action: outcome.action,
            })

            if (!options.dryRun && !stagingFailure) {
                try {
                    files.add(pair.sourcePath, pair.source)
                    files.add(pair.mapPath, serializeMapContent(pair.map))
                } catch (error) {
                    stagingFailure = { error }
                }
            }

            pass(owned)
        }
        const failure = hermesFailure ?? stagingFailure
        if (failure) {
            throw failure.error
        }
        files.commit()
    } catch (error) {
        files.discard()
        throw error
    }

    warnings.push(...hermesWarnings)
    if (!forProcess && options.releaseMode === 'symbol-set' && reported === null && withoutRelease) {
        warnings.push(MISSING_RELEASE_WARNING)
    }
    return { report: { release: reported, injected, skipped, warnings }, handoff }
}

const DRY_RUN_RELEASE_WARNING =
    'PostHog assigns the release ID, so a dry run leaves it out. JavaScript content hashes from a dry run can differ from a real run.'
const MISSING_RELEASE_WARNING =
    'No release could be resolved. Sourcemaps will upload without a release. Pass both --release-name and --release-version, or run from a git repository or supported CI environment.'

export interface UploadReport {
    dryRun: boolean
    release: ReleaseReport | null
    symbolSets: SymbolSetReport[]
    skipped: Skip[]
    warnings: string[]
    deletedMaps: string[]
}

interface Planned {
    artifact: Artifact
    upload: SymbolSetUpload
    policy: { force: boolean; skipOnConflict: boolean; batchSize: number }
}

function proguardGit(ctx: Context, artifact: Artifact): GitInfo | undefined {
    try {
        // posthog-cli resolves symlinks first, so a link outside the repository still finds it.
        return gitInfo(ctx.runtime.env, dirname(realpathSync(artifact.path)))
    } catch (error) {
        if (error instanceof GitError) {
            throw new HogError(
                'git_failed',
                `hog couldn't read the git repository: ${error.message}`,
                'Pass --release-name and --release-version.'
            )
        }
        throw error
    }
}

export async function upload(ctx: Context, selection: Selection, options: ErrorTrackingOptions): Promise<UploadReport> {
    const scratch = new Scratch()
    try {
        return await uploadArtifacts(ctx, selection, options, new Session(ctx), scratch)
    } finally {
        scratch.dispose()
    }
}

async function uploadArtifacts(
    ctx: Context,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session,
    scratch: Scratch,
    injected?: InjectReport,
    handoff?: Handoff
): Promise<UploadReport> {
    const skipped: Skip[] = [...(injected?.skipped ?? [])]
    const warnings: string[] = [...(injected?.warnings ?? [])]
    const releases = session.releases
    const fields = await releaseFields(ctx, options)
    const planned: Planned[] = []
    let reported: ReleaseReport | null = injected?.release ?? null

    const mappings = selection.artifacts.filter((artifact) => artifact.kind === 'proguard')
    if (mappings.length > 0) {
        const git = proguardGit(ctx, mappings[0]!)
        const { name, version } = resolveRelease(fields, git)
        let release: Release | undefined
        if (name !== undefined && version !== undefined) {
            reported = { name, version, id: null }
            if (!options.dryRun) {
                release = await releases.get(name, version, git)
                reported.id = release.id
            }
        }
        for (const artifact of mappings) {
            const chunkId = options.mapId ?? artifact.root.mapId
            if (!chunkId) {
                throw new HogError(
                    'map_id_required',
                    `${artifact.display} is a ProGuard mapping, which needs the map ID your build injected into the app.`,
                    'Pass --map-id, or set "mapId" on the source in posthog.json.',
                    EXIT_USAGE
                )
            }
            planned.push({
                artifact,
                upload: {
                    chunkId,
                    releaseId: release?.id ?? null,
                    data: proguardContainer(artifact.path, artifact.display),
                },
                policy: {
                    force: options.force,
                    skipOnConflict: options.skipOnConflict,
                    batchSize: options.batchSize ?? 50,
                },
            })
        }
    }

    // Metro bundles upload through their composed maps, so upload never reads their own pairs.
    const jsOnly = { ...selection, artifacts: selection.artifacts.filter((artifact) => artifact.kind === 'js') }
    const reader = new PairReader(options.publicPathPrefix)
    const pairs = (found: Skip[], read: 'read' | 'take'): Generator<OwnedPair> =>
        handoff && 'snapshot' in handoff ? handoff.snapshot.pairs() : readPairs(jsOnly, reader, found, read)
    const entryOptions: JsEntryOptions = {
        releaseMode: options.releaseMode,
        deleteAfter: options.deleteAfter,
        keep: options.dryRun ? sizeOnly : scratch.write,
    }
    const releaseWarnings: string[] = []
    const jsRelease = async (needed: boolean): Promise<string | undefined> => {
        const resolved = needed ? resolveJsRelease(fields, ctx.runtime.env, selection.cwd, releaseWarnings) : undefined
        if (!resolved) {
            return undefined
        }
        reported = { name: resolved.name, version: resolved.version, id: null }
        if (options.dryRun) {
            releaseWarnings.push(DRY_RUN_RELEASE_WARNING)
            return undefined
        }
        const release = await releases.get(resolved.name, resolved.version, resolved.git)
        reported.id = release.id
        return release.id
    }
    const collectEntries = (releaseId?: string): JsEntry[] => {
        const collected: JsEntry[] = []
        for (const owned of pairs(skipped, 'take')) {
            collected.push(jsEntry(owned, { ...entryOptions, releaseId }))
        }
        return collected
    }
    const reportJsRelease = async (collected: JsEntry[]): Promise<void> => {
        const needed =
            options.releaseMode === 'symbol-set' &&
            !injected?.release &&
            collected.length > 0 &&
            (releaseRequested(fields) || collected.some((entry) => entry.uploadable && entry.withoutRelease))
        await jsRelease(needed)
    }

    let entries: JsEntry[]
    let stampedRelease: string | undefined
    if (handoff && 'entries' in handoff) {
        entries = handoff.entries
        await reportJsRelease(entries)
        if (handoff.failure) {
            throw handoff.failure.error
        }
    } else if (uploadStampsRelease(options, injected?.release ?? null)) {
        // The release goes into every container, so it is settled before any container is built.
        const needed = releaseRequested(fields)
            ? some(pairs([], 'read'), () => true)
            : some(pairs([], 'read'), ({ pair }) => isUploadable(pair) && pair.map.releaseId === null)
        stampedRelease = await jsRelease(needed)
        entries = collectEntries(stampedRelease)
    } else {
        entries = collectEntries()
        await reportJsRelease(entries)
    }
    const uploadable = entries.filter((entry) => entry.uploadable)

    let targets: CleanupTarget[] = []
    // posthog-cli stops before any cleanup when no bundle has an id to upload under.
    let jsUploadable = false
    const composed = selection.artifacts.filter(
        (artifact) => artifact.kind === 'hermes' && !isHermesBundlePath(artifact.path)
    )
    if (options.releaseMode === 'event' && options.skipOnConflict && (entries.length > 0 || composed.length > 0)) {
        warnings.push(
            '--skip-on-conflict is ignored in event mode: every chunk is overwritten, so events never keep an old release.'
        )
    }
    if (entries.length > 0) {
        jsUploadable = uploadable.length > 0
        if (!jsUploadable) {
            warnings.push(
                'No bundle has a chunk ID or a native debug ID, so there is nothing to upload. Run `hog error-tracking inject` first.'
            )
        }
        if (options.deleteAfter) {
            targets = uploadable.map((entry) => entry.target!)
        }
        warnings.push(...releaseWarnings)
        if (
            options.releaseMode === 'symbol-set' &&
            (!options.dryRun || reported === null) &&
            stampedRelease === undefined &&
            uploadable.some((entry) => entry.withoutRelease)
        ) {
            warnings.push(MISSING_RELEASE_WARNING)
        }
        const prepared = dropDuplicateChunks(
            entries.flatMap(({ artifact, prepared }) => {
                if ('skip' in prepared) {
                    skipped.push(prepared.skip)
                    return []
                }
                return [{ artifact, ...prepared }]
            })
        )
        for (const chunkId of prepared.duplicates) {
            warnings.push(`Duplicate chunk ID ${chunkId} across symbol sets: hog uploads the first one.`)
        }
        // Event mode always replaces what PostHog has, because the payload changes with each release.
        const policy = {
            ...(options.releaseMode === 'event'
                ? { force: true, skipOnConflict: false }
                : { force: options.force, skipOnConflict: options.skipOnConflict }),
            batchSize: options.batchSize ?? 50,
        }
        for (const { artifact, upload: item } of prepared.uploads) {
            planned.push({ artifact, upload: item, policy })
        }
    }

    if (composed.length > 0) {
        if (options.releaseMode === 'event' && !(fields.name && fields.version && fields.build)) {
            warnings.push(
                'In event mode, exceptions take their release from the app. Pass --release-name, --release-version and --build matching the app identifier, version and build number, or exceptions will report no release.'
            )
        }
        // Every map is read before the release is settled, because a map that carries a release
        // decides whether one is created. Only its ids stay in memory, and the rest waits on disk.
        const maps = composed.map((artifact) => {
            const map = storeHermesMap(artifact.path, scratch)
            collect()
            return { artifact, ...map }
        })
        // posthog-cli creates the release even in event mode, so PostHog has a row to match the
        // app metadata of an event to.
        let releaseId: string | null = null
        if (releaseRequested(fields) || maps.some(({ map }) => map.releaseId === null)) {
            const start = resolve(selection.cwd, composed[0]!.root.path)
            const resolved = resolveJsRelease(fields, ctx.runtime.env, start, warnings)
            if (resolved) {
                reported = { name: resolved.name, version: resolved.version, id: null }
                if (!options.dryRun) {
                    releaseId = (await releases.get(resolved.name, resolved.version, resolved.git)).id
                    reported.id = releaseId
                }
            }
        }
        const policy = {
            ...(options.releaseMode === 'event'
                ? { force: true, skipOnConflict: false }
                : { force: options.force, skipOnConflict: options.skipOnConflict }),
            batchSize: options.batchSize ?? 50,
        }
        let uploadable = 0
        for (const { artifact, map, reason, body } of maps) {
            if (reason || body === undefined) {
                skipped.push({
                    path: artifact.display,
                    reason:
                        reason === 'no_chunk_id'
                            ? 'the map has no chunk ID. Run `hog error-tracking clone` after the Hermes build.'
                            : 'the sourcemap is empty. Check your bundler sourcemap setting.',
                })
                continue
            }
            map.releaseId = options.releaseMode === 'event' ? null : (releaseId ?? map.releaseId)
            planned.push({
                artifact,
                upload: hermesUpload(map, body, options.dryRun ? sizeOnly : scratch.write),
                policy,
            })
            collect()
            uploadable++
        }
        if (uploadable === 0) {
            throw new HogError(
                'no_hermes_chunk_ids',
                'None of the Hermes maps has a chunk ID, so nothing was uploaded.',
                'Run `hog error-tracking inject` on the Metro bundle before the Hermes build, and `hog error-tracking clone` after it.'
            )
        }
    }

    const nativeArtifacts = selection.artifacts.filter(
        (artifact) => artifact.kind === 'elf' || artifact.kind === 'dsym'
    )
    if (nativeArtifacts.length > 0) {
        const before = skipped.length
        const native = packageNative(
            nativeArtifacts,
            selection.cwd,
            options.includeSource,
            options.dryRun ? sizeOnly : scratch.write,
            skipped,
            warnings
        )
        if (native.length === 0 && planned.length === 0) {
            const details = skipped
                .slice(before)
                .map((skip) => `\n  ${skip.path}: ${skip.reason}`)
                .join('')
            throw new HogError(
                'no_debug_symbols',
                `None of the native files or dSYM bundles could be uploaded:${details}`,
                'Build with debug info and a build ID, and upload before stripping.'
            )
        }
        // Like `symbol-sets upload`, the release comes from the flags, then git around the first
        // path. A git error only drops the git metadata.
        let git: GitInfo | undefined
        try {
            git = gitInfo(ctx.runtime.env, resolve(selection.cwd, nativeArtifacts[0]!.root.path))
        } catch (error) {
            if (!(error instanceof GitError)) {
                throw error
            }
        }
        const { name, version } = resolveRelease(fields, git)
        let releaseId: string | null = null
        if (name !== undefined && version !== undefined) {
            reported = { name, version, id: null }
            if (!options.dryRun) {
                releaseId = (await releases.get(name, version, git)).id
                reported.id = releaseId
            }
        }
        // posthog-cli forces source bundles, because the files on disk change between runs of one build.
        const policy = {
            force: options.force || (options.includeSource && !options.skipOnConflict),
            skipOnConflict: options.skipOnConflict,
            batchSize: options.batchSize ?? 10,
        }
        for (const { artifact, upload: item } of native) {
            planned.push({ artifact, upload: { ...item, releaseId }, policy })
        }
    }

    if (
        options.releaseMode === 'symbol-set' &&
        !warnings.includes(MISSING_RELEASE_WARNING) &&
        (!options.dryRun || reported === null) &&
        planned.some(({ artifact, upload }) => artifact.kind === 'hermes' && !upload.releaseId)
    ) {
        warnings.push(MISSING_RELEASE_WARNING)
    }

    // posthog-cli's Hermes upload fails when it finds nothing to upload, so a build step that lost
    // its composed maps doesn't pass while every exception stays unreadable.
    if (composed.length === 0 && selection.artifacts.some((artifact) => artifact.kind === 'hermes')) {
        const message = 'hog found Hermes bundles but no composed Hermes sourcemaps'
        const hint =
            'Run `hog error-tracking clone` after the Hermes build, and upload the folder with its composed maps.'
        if (planned.length === 0) {
            throw new HogError('no_hermes_maps', `${message}, so nothing was uploaded.`, hint)
        }
        warnings.push(`${message}, so their stack traces stay unreadable. ${hint}`)
    }

    const report = (item: Planned, status: SymbolSetReport['status']): SymbolSetReport => ({
        path: item.artifact.display,
        kind: item.artifact.kind,
        chunkId: item.upload.chunkId,
        contentHash: item.upload.contentHash ?? contentHash(uploadBytes(item.upload.data)),
        size: item.upload.data.length,
        status,
    })
    if (options.dryRun) {
        return {
            dryRun: true,
            release: reported,
            symbolSets: planned.map((item) => report(item, 'planned')),
            skipped,
            warnings,
            deletedMaps: [],
        }
    }

    const statuses = new Map<string, UploadStatus>()
    const groups = new Map<string, Planned[]>()
    for (const item of planned) {
        const key = `${item.policy.force}:${item.policy.skipOnConflict}:${item.policy.batchSize}`
        const group = groups.get(key)
        if (group) {
            group.push(item)
        } else {
            groups.set(key, [item])
        }
    }
    // posthog-cli's upload events, so its dashboards keep working. `type` was plain or hermes there.
    const kinds: Record<string, number> = {}
    for (const item of planned) {
        kinds[item.artifact.kind] = (kinds[item.artifact.kind] ?? 0) + 1
    }
    const kindNames = Object.keys(kinds)
    const uploadProperties = {
        type: kindNames.length === 1 ? (kindNames[0] === 'js' ? 'plain' : kindNames[0]) : 'mixed',
        kinds,
        file_count: planned.length,
        total_bytes: planned.reduce((sum, item) => sum + item.upload.data.length, 0),
    }
    ctx.telemetry.capture('error_tracking_cli_sourcemaps_upload_started', uploadProperties)
    const uploadStarted = ctx.runtime.now()
    const finished = (error?: unknown): void => {
        const counts = [...statuses.values()]
        ctx.telemetry.capture('error_tracking_cli_sourcemaps_upload_finished', {
            ...uploadProperties,
            duration_ms: ctx.runtime.now() - uploadStarted,
            success: error === undefined,
            uploaded: counts.filter((status) => status === 'uploaded').length,
            skipped_already_present: counts.filter((status) => status === 'already_present').length,
            skipped_too_large: counts.filter((status) => status === 'too_large').length,
            error_code: error === undefined ? null : error instanceof HogError ? error.code : 'internal_error',
        })
    }
    try {
        for (const group of groups.values()) {
            const client = await session.getClient()
            await client.upload(
                group.map((item) => item.upload),
                { concurrency: options.concurrency, ...group[0]!.policy, progress: statuses }
            )
        }
    } catch (error) {
        finished(error)
        throw error
    }
    finished()

    let deletedMaps: string[] = []
    if (options.deleteAfter && jsUploadable) {
        const rootPaths = selection.roots.map((root) => resolve(selection.cwd, root.path))
        const ignored = (mapPath: string): boolean =>
            selection.roots.some((root, index) =>
                isIgnored(root, realpathSync(rootPaths[index]!), realpathSync(mapPath))
            )
        const cleanup = cleanUp([
            // Maps skipped as too large go too, as in posthog-cli, so they never ship with the build.
            ...targets,
            ...cssTargets(
                listFiles(selection.roots, selection.cwd),
                rootPaths,
                options.publicPathPrefix,
                warnings,
                ignored
            ),
        ])
        deletedMaps = cleanup.deletedMaps.map((path) => relative(realpathSync(selection.cwd), path))
        warnings.push(...cleanup.warnings)
    }
    return {
        dryRun: false,
        release: reported,
        symbolSets: planned.map((item) => report(item, statuses.get(item.upload.chunkId) ?? 'already_present')),
        skipped,
        warnings,
        deletedMaps,
    }
}

function storeHermesMap(
    path: string,
    scratch: Scratch
): { map: MapIds; reason: HermesMapSkip | undefined; body: StoredData | undefined } {
    const { body, ...map } = readHermesMap(readFileSync(path), 'all')
    const reason = hermesSkipReason(map)
    return { map, reason, body: reason === undefined ? scratch.write(...body) : undefined }
}

// `process`: posthog-cli creates the release first when the flags name one, so a failure there
// stops the run before any file changes. Otherwise inject resolves it from git as usual.
export async function processArtifacts(
    ctx: Context,
    selection: Selection,
    options: ErrorTrackingOptions
): Promise<UploadReport & { injected: InjectedReport[] }> {
    const session = new Session(ctx)
    const fields = await releaseFields(ctx, options)
    let preset: Release | undefined
    if (releaseRequested(fields) && !options.dryRun) {
        const resolved = resolveJsRelease(fields, ctx.runtime.env, selection.cwd, [])
        if (resolved) {
            preset = await session.releases.get(resolved.name, resolved.version, resolved.git)
        }
    }
    const scratch = new Scratch()
    try {
        const injected = selection.artifacts.some(isBundle)
            ? await injectPairs(ctx, selection, options, session, { preset, scratch })
            : undefined
        const report = await uploadArtifacts(
            ctx,
            selection,
            options,
            session,
            scratch,
            injected?.report,
            injected?.handoff
        )
        return { ...report, injected: injected?.report.injected ?? [] }
    } finally {
        scratch.dispose()
    }
}

export interface CloneReport {
    dryRun: boolean
    release: ReleaseReport | null
    warnings: string[]
    from: string
    to: string
    chunkId: string | null
    releaseId: string | null
}

function readMap(cwd: string, path: string, role: string, parts: 'ids' | 'all'): { path: string; map: HermesMap } {
    const full = resolve(cwd, path)
    try {
        return { path: full, map: readHermesMap(readFileSync(full), parts) }
    } catch (error) {
        throw new HogError('map_unreadable', `hog couldn't read the ${role} map ${path}: ${(error as Error).message}`)
    }
}

export async function cloneMaps(
    ctx: Context,
    fromPath: string,
    toPath: string,
    options: ErrorTrackingOptions
): Promise<CloneReport> {
    const cwd = ctx.runtime.cwd()
    // Both maps are read before the release is settled, so a broken map stops the command before
    // it creates one. The packager map is read for its ids, and again only if its release changes.
    const from = readMap(cwd, fromPath, 'packager', 'ids')
    collect()
    const to = readMap(cwd, toPath, 'composed', options.dryRun ? 'ids' : 'all')
    const warnings: string[] = []
    let reported: ReleaseReport | null = null
    let releaseId: string | null = null
    if (options.releaseMode === 'symbol-set') {
        // Without release flags, the release `inject` stamped stays, and the upload binds to it.
        releaseId = from.map.releaseId
        const fields = await releaseFields(ctx, options)
        if (releaseRequested(fields) || from.map.releaseId === null) {
            const resolved = resolveJsRelease(fields, ctx.runtime.env, from.path, warnings)
            if (resolved) {
                reported = { name: resolved.name, version: resolved.version, id: null }
                if (!options.dryRun) {
                    releaseId = (await new Session(ctx).releases.get(resolved.name, resolved.version, resolved.git)).id
                    reported.id = releaseId
                }
            }
        }
    }
    if (options.releaseMode === 'symbol-set' && releaseId === null && reported === null) {
        warnings.push(MISSING_RELEASE_WARNING)
    }
    const fromChanged = from.map.releaseId !== releaseId
    from.map.releaseId = releaseId
    cloneMetadata(from.map, to.map)
    if (!options.dryRun) {
        if (fromChanged) {
            const { body } = readMap(cwd, fromPath, 'packager', 'all').map
            writeFileSync(from.path, hermesMapBytes(from.map, body))
        }
        writeFileSync(to.path, hermesMapBytes(to.map, to.map.body))
    }
    return {
        dryRun: options.dryRun,
        release: reported,
        warnings,
        from: fromPath,
        to: toPath,
        chunkId: to.map.chunkId,
        releaseId: to.map.releaseId,
    }
}

const NATIVE_PROBLEMS: Record<NativeProblem, string> = {
    no_debug_info: 'it has no debug info. Build with debug info, and upload before stripping it.',
    no_build_id:
        "it has no GNU build ID, so crashes can't be matched to it. Link with `-Wl,--build-id=sha1`. Go needs `-ldflags=-B=gobuildid`.",
    missing_uuid: "it has no LC_UUID, so crashes can't be matched to it. Link without `-no_uuid`.",
    compressed_dwarf:
        "its DWARF is compressed (`__zdebug` sections), which PostHog can't read yet. Go needs `-ldflags=-compressdwarf=false` on macOS.",
    unparseable_slice: "one of its architectures can't be parsed, so hog skips that architecture.",
}

// A path the DWARF names can reach the source folder through a symlink, or the folder can be one,
// so the globs match the path as written and its canonical form, and either one ignores it.
function sourceIgnored(root: Root, folder: string): (path: string) => boolean {
    const canonical = (path: string): string => {
        try {
            return realpathSync(path)
        } catch {
            return path
        }
    }
    const realFolder = canonical(folder)
    return (path) => isIgnored(root, folder, path) || isIgnored(root, realFolder, canonical(path))
}

// `symbol-sets upload`: native files are parsed and deduplicated by debug ID, dSYM bundles are
// split per slice, and a dSYM wins over a native file with the same ID.
function packageNative(
    artifacts: Artifact[],
    cwd: string,
    includeSource: boolean,
    keep: KeepData,
    skipped: Skip[],
    warnings: string[]
): { artifact: Artifact; upload: SymbolSetUpload }[] {
    const owners = new Map<SymbolSetUpload, Artifact>()
    const files: { file: NativeFile; artifact: Artifact }[] = []
    for (const artifact of artifacts.filter((candidate) => !isDsymBundle(candidate.path))) {
        let candidates
        try {
            candidates = nativeCandidates(artifact.path)
        } catch (error) {
            skipped.push({ path: artifact.display, reason: `hog couldn't parse it: ${(error as Error).message}` })
            continue
        }
        for (const candidate of candidates) {
            if ('problem' in candidate) {
                skipped.push({ path: artifact.display, reason: NATIVE_PROBLEMS[candidate.problem] })
            } else {
                files.push({ file: candidate.file, artifact })
            }
        }
    }
    const byFile = new Map(files.map(({ file, artifact }) => [file, artifact]))
    const natives = dedupeNativeFiles(
        files.map(({ file }) => file),
        (dropped, kept) =>
            skipped.push({
                path: byFile.get(dropped)!.display,
                reason: `${byFile.get(kept)!.display} has the same debug ID and is at least as large, so hog uploads that one.`,
                intended: true,
            })
    ).map((file) => {
        const { root } = byFile.get(file)!
        const folder = resolve(cwd, root.path)
        const sources = includeSource
            ? sourceStep(file.data, 'native', warnings, sourceIgnored(root, folder))
            : undefined
        const upload = nativeUpload(file, keep, sources)
        owners.set(upload, byFile.get(file)!)
        return upload
    })
    const dsyms: SymbolSetUpload[] = []
    for (const artifact of artifacts.filter((candidate) => isDsymBundle(candidate.path))) {
        try {
            // Sources come from the whole binary, so every slice of a fat binary carries all of them.
            const steps = new Map<string, ReturnType<typeof sourceStep>>()
            const folder = resolve(cwd, artifact.root.path)
            const uploads: SymbolSetUpload[] = []
            for (const slice of dsymSlices(artifact.path, (member) => !isIgnored(artifact.root, folder, member))) {
                if (includeSource && !steps.has(slice.path)) {
                    steps.set(
                        slice.path,
                        sourceStep(slice.file, 'dsym', warnings, sourceIgnored(artifact.root, folder))
                    )
                }
                uploads.push(dsymUpload(slice, keep, steps.get(slice.path)))
            }

            for (const upload of uploads) {
                owners.set(upload, artifact)
                dsyms.push(upload)
            }
        } catch (error) {
            skipped.push({ path: artifact.display, reason: `hog couldn't read the dSYM: ${(error as Error).message}` })
        }
    }
    const merged = mergePreferDsym(dsyms, natives, (dropped) =>
        skipped.push({
            path: owners.get(dropped)!.display,
            reason: `a dSYM bundle has the same UUID ${dropped.chunkId}, so hog uploads the bundle.`,
            intended: true,
        })
    )
    return merged.map((upload) => ({ artifact: owners.get(upload)!, upload }))
}
