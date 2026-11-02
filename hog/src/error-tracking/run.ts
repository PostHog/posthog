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
    injectEventMode,
    injectSymbolSetMode,
    preparePairs,
    randomChunkId,
    releaseRequested,
    resolveJsRelease,
    savePairs,
    type InjectAction,
} from './js-flow'
import { decodeUtf8 } from './json'
import { cloneMetadata, hermesSkipReason, hermesUpload, isHermesBundlePath } from './kinds/hermes'
import {
    loadMapContent,
    readPair,
    serializeMapContent,
    type MapContent,
    type ReleaseMode,
    type Skip,
    type SourcePair,
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
import { SymbolSetClient, type SymbolSetUpload, type UploadStatus } from './upload'

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
            .credentials()
            .then(
                (credentials) =>
                    new SymbolSetClient(this.ctx.runtime, credentials, () =>
                        this.ctx.telemetry.capture('error_tracking_cli_sourcemaps_upload_endpoint_fallback')
                    )
            )
        return this.client
    }
}

const isBundle = (artifact: Artifact): boolean =>
    artifact.kind === 'js' || (artifact.kind === 'hermes' && isHermesBundlePath(artifact.path))

function readPairs(
    selection: Selection,
    options: ErrorTrackingOptions,
    skipped: Skip[]
): { pairs: SourcePair[]; artifacts: Map<SourcePair, Artifact> } {
    const seen = new Set<string>()
    const pairs: SourcePair[] = []
    const owners = new Map<SourcePair, Artifact>()
    for (const artifact of selection.artifacts.filter(isBundle)) {
        const pair = readPair(artifact.path, options.publicPathPrefix, skipped)
        if (
            pair &&
            isIgnored(
                artifact.root,
                realpathSync(resolve(selection.cwd, artifact.root.path)),
                realpathSync(pair.mapPath)
            )
        ) {
            skipped.push({ path: artifact.display, reason: `its sourcemap matches an ignore pattern in posthog.json` })
            continue
        }
        if (pair && !seen.has(pair.sourcePath)) {
            seen.add(pair.sourcePath)
            pairs.push(pair)
            owners.set(pair, artifact)
        }
    }
    return { pairs, artifacts: owners }
}

export interface InjectReport {
    release: ReleaseReport | null
    injected: InjectedReport[]
    skipped: Skip[]
    warnings: string[]
    pairs: SourcePair[]
    owners: Map<SourcePair, Artifact>
}

export async function inject(
    ctx: Context,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session = new Session(ctx),
    preset?: Release
): Promise<InjectReport> {
    const skipped: Skip[] = []
    const warnings: string[] = []
    const { pairs, artifacts: owners } = readPairs(selection, options, skipped)
    if (pairs.length === 0) {
        throw new HogError(
            'no_bundles',
            'hog found no JavaScript or Hermes bundles with sourcemaps to inject in those paths.',
            'Check the paths, or pass --public-path-prefix if your sourceMappingURL comments are absolute URLs.'
        )
    }
    // Hermes bundles never carry a release in event mode: the app's own metadata names it.
    const hermes = new Set(pairs.filter((pair) => owners.get(pair)?.kind === 'hermes'))
    const js = pairs.filter((pair) => !hermes.has(pair))
    const fields = await releaseFields(ctx, options)
    let release = preset
    let reported: ReleaseReport | null = release
        ? { name: release.project, version: release.version, id: release.id }
        : null
    if (!release) {
        const needed =
            options.releaseMode === 'event'
                ? js.length > 0
                : releaseRequested(fields) || pairs.some((pair) => pair.map.releaseId === null)
        const resolved = needed ? resolveJsRelease(fields, ctx.runtime.env, selection.cwd, warnings) : undefined
        if (resolved) {
            reported = { name: resolved.name, version: resolved.version, id: null }
            if (options.dryRun) {
                warnings.push(DRY_RUN_RELEASE_WARNING)
            } else {
                release = await session.releases.get(resolved.name, resolved.version, resolved.git)
                reported.id = release.id
            }
        } else if (options.releaseMode === 'event' && js.length > 0) {
            warnings.push(
                'No release could be resolved, so hog injected chunk IDs only and events will carry no release.'
            )
        }
    }
    const releaseId = release?.id ?? null
    const byPair = new Map(
        (options.releaseMode === 'event'
            ? [...injectEventMode(js, releaseId, warnings), ...injectEventMode([...hermes], null, warnings)]
            : injectSymbolSetMode(pairs, releaseId, randomChunkId(ctx.runtime.now))
        ).map((outcome) => [outcome.pair, outcome])
    )
    const outcomes = pairs.map((pair) => byPair.get(pair)!)
    if (!options.dryRun) {
        savePairs(pairs, (pair) => serializeMapContent(pair.map))
    }
    return {
        release: reported,
        injected: outcomes.map((outcome) => ({
            path: owners.get(outcome.pair)?.display ?? outcome.pair.sourcePath,
            map: relative(realpathSync(selection.cwd), outcome.pair.mapPath),
            chunkId: outcome.chunkId,
            action: outcome.action,
        })),
        skipped,
        warnings,
        pairs,
        owners,
    }
}

const DRY_RUN_RELEASE_WARNING =
    'PostHog assigns the release ID, so a dry run leaves it out. JavaScript content hashes from a dry run can differ from a real run.'

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

export async function upload(
    ctx: Context,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session = new Session(ctx),
    injected?: InjectReport
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
    const read = injected ? { pairs: injected.pairs, artifacts: injected.owners } : readPairs(jsOnly, options, skipped)
    read.pairs = read.pairs.filter((pair) => read.artifacts.get(pair)?.kind === 'js')
    let targets: { pair: SourcePair; target: CleanupTarget }[] = []
    // posthog-cli stops before any cleanup when no bundle has an id to upload under.
    let jsUploadable = false
    const composed = selection.artifacts.filter(
        (artifact) => artifact.kind === 'hermes' && !isHermesBundlePath(artifact.path)
    )
    if (options.releaseMode === 'event' && options.skipOnConflict && (read.pairs.length > 0 || composed.length > 0)) {
        warnings.push(
            '--skip-on-conflict is ignored in event mode: every chunk is overwritten, so events never keep an old release.'
        )
    }
    if (read.pairs.length > 0) {
        const uploadable = read.pairs.filter((pair) => pair.chunkId() !== null || pair.debugId() !== null)
        jsUploadable = uploadable.length > 0
        if (!jsUploadable) {
            warnings.push(
                'No bundle has a chunk ID or a native debug ID, so there is nothing to upload. Run `hog error-tracking inject` first.'
            )
        }
        if (options.deleteAfter) {
            targets = uploadable.map((pair) => ({ pair, target: jsTarget(pair) }))
        }
        if (
            options.releaseMode === 'symbol-set' &&
            !injected?.release &&
            (releaseRequested(fields) || uploadable.some((pair) => pair.map.releaseId === null))
        ) {
            const resolved = resolveJsRelease(fields, ctx.runtime.env, selection.cwd, warnings)
            if (resolved) {
                reported = { name: resolved.name, version: resolved.version, id: null }
                if (options.dryRun) {
                    warnings.push(DRY_RUN_RELEASE_WARNING)
                } else {
                    const release = await releases.get(resolved.name, resolved.version, resolved.git)
                    reported.id = release.id
                    for (const pair of uploadable) {
                        pair.map.releaseId = release.id
                    }
                }
            }
        }
        const prepared = preparePairs(read.pairs, options.releaseMode)
        skipped.push(...prepared.skipped)
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
        for (const { pair, upload: item } of prepared.uploads) {
            planned.push({ artifact: read.artifacts.get(pair)!, upload: item, policy })
        }
    }

    if (composed.length > 0) {
        if (options.releaseMode === 'event' && !(fields.name && fields.version && fields.build)) {
            warnings.push(
                'In event mode, exceptions take their release from the app. Pass --release-name, --release-version and --build matching the app identifier, version and build number, or exceptions will report no release.'
            )
        }
        const maps = composed.map((artifact) => ({
            artifact,
            map: loadMapContent(decodeUtf8(readFileSync(artifact.path))),
        }))
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
        for (const { artifact, map } of maps) {
            const reason = hermesSkipReason(map)
            if (reason) {
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
            planned.push({ artifact, upload: hermesUpload(map), policy })
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
        const native = packageNative(nativeArtifacts, selection.cwd, options.includeSource, skipped, warnings)
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
        contentHash: item.upload.contentHash ?? contentHash(item.upload.data),
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
            ...targets.map(({ target }) => target),
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
    const injected = selection.artifacts.some(isBundle)
        ? await inject(ctx, selection, options, session, preset)
        : undefined
    const report = await upload(ctx, selection, options, session, injected)
    return { ...report, injected: injected?.injected ?? [] }
}

export interface CloneReport {
    dryRun: boolean
    release: ReleaseReport | null
    from: string
    to: string
    chunkId: string | null
    releaseId: string | null
}

function readMap(cwd: string, path: string, role: string): { path: string; map: MapContent } {
    const full = resolve(cwd, path)
    try {
        return { path: full, map: loadMapContent(decodeUtf8(readFileSync(full))) }
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
    const from = readMap(cwd, fromPath, 'packager')
    const to = readMap(cwd, toPath, 'composed')
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
    const fromChanged = from.map.releaseId !== releaseId
    from.map.releaseId = releaseId
    cloneMetadata(from.map, to.map)
    if (!options.dryRun) {
        if (fromChanged) {
            writeFileSync(from.path, serializeMapContent(from.map))
        }
        writeFileSync(to.path, serializeMapContent(to.map))
    }
    return {
        dryRun: options.dryRun,
        release: reported,
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
            })
    ).map((file) => {
        const { root } = byFile.get(file)!
        const folder = resolve(cwd, root.path)
        const sources = includeSource
            ? sourceStep(file.data, 'native', warnings, sourceIgnored(root, folder))
            : undefined
        const upload = nativeUpload(file, sources)
        owners.set(upload, byFile.get(file)!)
        return upload
    })
    const dsyms: SymbolSetUpload[] = []
    for (const artifact of artifacts.filter((candidate) => isDsymBundle(candidate.path))) {
        try {
            // Sources come from the whole binary, so every slice of a fat binary carries all of them.
            const steps = new Map<string, ReturnType<typeof sourceStep>>()
            const folder = resolve(cwd, artifact.root.path)
            const slices = dsymSlices(artifact.path, (member) => !isIgnored(artifact.root, folder, member))
            const uploads = slices.map((slice) => {
                if (includeSource && !steps.has(slice.path)) {
                    steps.set(
                        slice.path,
                        sourceStep(slice.file, 'dsym', warnings, sourceIgnored(artifact.root, folder))
                    )
                }
                return dsymUpload(slice, steps.get(slice.path))
            })
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
        })
    )
    return merged.map((upload) => ({ artifact: owners.get(upload)!, upload }))
}
