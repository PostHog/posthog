import { realpathSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'

import { cleanUp, cssTargets, jsTarget, type CleanupTarget } from './cleanup'
import { contentHash } from './container'
import { discover, listFiles, type Artifact, type Root } from './discover'
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
import { readPair, serializeMapContent, type ReleaseMode, type Skip, type SourcePair } from './kinds/js'
import { proguardContainer } from './kinds/proguard'
import { fetchOrCreateRelease, resolveRelease, type Release, type ReleaseFields } from './release'
import { SymbolSetClient, type SymbolSetUpload, type UploadStatus } from './upload'

export interface ErrorTrackingOptions {
    kind?: ArtifactKind
    mapId?: string
    release: ReleaseFields
    releaseMode: ReleaseMode
    publicPathPrefix?: string
    force: boolean
    skipOnConflict: boolean
    batchSize: number
    concurrency: number
    deleteAfter: boolean
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

export async function releaseFields(ctx: Context, options: ErrorTrackingOptions): Promise<ReleaseFields> {
    const configured = (await ctx.config())?.config.errorTracking?.release
    return {
        name: options.release.name ?? configured?.name,
        version: options.release.version ?? configured?.version,
        build: options.release.build,
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
        this.client ??= this.ctx.credentials().then((credentials) => new SymbolSetClient(this.ctx.runtime, credentials))
        return this.client
    }
}

function readPairs(
    artifacts: Artifact[],
    options: ErrorTrackingOptions,
    skipped: Skip[]
): { pairs: SourcePair[]; artifacts: Map<SourcePair, Artifact> } {
    const seen = new Set<string>()
    const pairs: SourcePair[] = []
    const owners = new Map<SourcePair, Artifact>()
    for (const artifact of artifacts.filter((candidate) => candidate.kind === 'js')) {
        const pair = readPair(artifact.path, options.publicPathPrefix, skipped)
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
    const { pairs, artifacts: owners } = readPairs(selection.artifacts, options, skipped)
    if (pairs.length === 0) {
        throw new HogError(
            'no_bundles',
            'hog found no JavaScript bundles with sourcemaps to inject in those paths.',
            'Check the paths, or pass --public-path-prefix if your sourceMappingURL comments are absolute URLs.'
        )
    }
    const fields = await releaseFields(ctx, options)
    let release = preset
    let reported: ReleaseReport | null = release
        ? { name: release.project, version: release.version, id: release.id }
        : null
    if (!release) {
        const needed =
            options.releaseMode === 'event' ||
            releaseRequested(fields) ||
            pairs.some((pair) => pair.map.releaseId === null)
        const resolved = needed ? resolveJsRelease(fields, ctx.runtime.env, selection.cwd, warnings) : undefined
        if (resolved) {
            reported = { name: resolved.name, version: resolved.version, id: null }
            if (options.dryRun) {
                warnings.push(DRY_RUN_RELEASE_WARNING)
            } else {
                release = await session.releases.get(resolved.name, resolved.version, resolved.git)
                reported.id = release.id
            }
        } else if (options.releaseMode === 'event') {
            warnings.push(
                'No release could be resolved, so hog injected chunk IDs only and events will carry no release.'
            )
        }
    }
    const releaseId = release?.id ?? null
    const outcomes =
        options.releaseMode === 'event'
            ? injectEventMode(pairs, releaseId, warnings)
            : injectSymbolSetMode(pairs, releaseId, randomChunkId(ctx.runtime.now))
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
    policy: { force: boolean; skipOnConflict: boolean }
}

function proguardGit(ctx: Context, artifact: Artifact): GitInfo | undefined {
    try {
        return gitInfo(ctx.runtime.env, dirname(artifact.path))
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
            const chunkId = artifact.root.mapId ?? options.mapId
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
                policy: { force: options.force, skipOnConflict: options.skipOnConflict },
            })
        }
    }

    const read = injected
        ? { pairs: injected.pairs, artifacts: injected.owners }
        : readPairs(selection.artifacts, options, skipped)
    let targets: CleanupTarget[] = []
    // posthog-cli stops before any cleanup when no bundle has an id to upload under.
    let jsUploadable = false
    if (read.pairs.length > 0) {
        if (options.releaseMode === 'event' && options.skipOnConflict) {
            warnings.push(
                '--skip-on-conflict is ignored in event mode: every chunk is overwritten, so events never keep an old release.'
            )
        }
        const uploadable = read.pairs.filter((pair) => pair.chunkId() !== null || pair.debugId() !== null)
        jsUploadable = uploadable.length > 0
        if (!jsUploadable) {
            warnings.push(
                'No bundle has a chunk ID or a native debug ID, so there is nothing to upload. Run `hog error-tracking inject` first.'
            )
        }
        if (options.deleteAfter) {
            targets = uploadable.map(jsTarget)
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
        const policy =
            options.releaseMode === 'event'
                ? { force: true, skipOnConflict: false }
                : { force: options.force, skipOnConflict: options.skipOnConflict }
        for (const { pair, upload: item } of prepared.uploads) {
            planned.push({ artifact: read.artifacts.get(pair)!, upload: item, policy })
        }
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
        const key = `${item.policy.force}:${item.policy.skipOnConflict}`
        groups.set(key, [...(groups.get(key) ?? []), item])
    }
    for (const group of groups.values()) {
        const client = await session.getClient()
        const outcome = await client.upload(
            group.map((item) => item.upload),
            { batchSize: options.batchSize, concurrency: options.concurrency, ...group[0]!.policy }
        )
        for (const [chunkId, status] of outcome.status) {
            statuses.set(chunkId, status)
        }
    }

    let deletedMaps: string[] = []
    if (options.deleteAfter && jsUploadable) {
        const rootPaths = selection.roots.map((root) => resolve(selection.cwd, root.path))
        const cleanup = cleanUp([
            ...targets,
            ...cssTargets(listFiles(selection.roots, selection.cwd), rootPaths, warnings),
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
    const hasJs = selection.artifacts.some((artifact) => artifact.kind === 'js')
    const injected = hasJs ? await inject(ctx, selection, options, session, preset) : undefined
    const report = await upload(ctx, selection, options, session, injected)
    return { ...report, injected: injected?.injected ?? [] }
}
