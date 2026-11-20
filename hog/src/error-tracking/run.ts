import { mkdtempSync, realpathSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'

import { discover, isHermesBundlePath, isIgnored, listFiles, type Artifact, type Root } from './discover'
import { GitError, gitInfo, type GitInfo } from './git'
import { packageNative } from './native'
import { injectPairs, isBundle, preparePairs, readPairs, type InjectedPairs, type OwnedPair } from './pairs'
import { resolveRelease, type Release } from './release'
import {
    DRY_RUN_RELEASE_WARNING,
    MISSING_RELEASE_WARNING,
    releaseFields,
    releaseRequested,
    resolveJsRelease,
    Session,
    type ErrorTrackingOptions,
    type InjectedReport,
    type ReleaseReport,
    type Selection,
    type Skip,
} from './session'
import type { SymbolSetFile, UploadStatus } from './upload'
import type { MapAnswer, MapState, Worker } from './worker'

export interface SymbolSetReport {
    path: string
    kind: ArtifactKind
    chunkId: string
    contentHash: string
    size: number
    status: UploadStatus | 'planned'
}

export async function select(
    ctx: Context,
    worker: Worker,
    paths: string[],
    options: ErrorTrackingOptions
): Promise<Selection> {
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
    const artifacts = await discover(worker, roots, cwd, { publicPathPrefix: options.publicPathPrefix })
    return { artifacts, roots, cwd }
}

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
    upload: SymbolSetFile
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

const CONTAINER_FOLDER_PREFIX = 'hog-upload-'
const CONTAINER_EXTENSION = 'symbolset'
const CSS_EXTENSION = '.css'

// Expo stamps only a `debugId` on the packager map, so a Hermes map uploads under it when it has
// no chunk ID.
const uploadChunkId = (map: MapState): string | null => map.chunkId ?? map.debugId

const hasUploadId = ({ pair }: OwnedPair): boolean =>
    pair.chunkId !== null || pair.sourceDebugId !== null || pair.mapDebugId !== null
const pairIds = (pairs: OwnedPair[]): number[] => pairs.map(({ pair }) => pair.id)
const withoutRelease = ({ pair }: OwnedPair): boolean => pair.mapReleaseId === null

async function proguardUpload(
    worker: Worker,
    artifact: Artifact,
    file: string | null
): Promise<{ file: string | null; size: number; contentHash: string }> {
    const built = await worker.proguard(artifact.path, file)
    if (!('invalid' in built)) {
        return { file, ...built }
    }

    if (built.invalid === 'not_utf8') {
        throw new HogError(
            'invalid_proguard_mapping',
            `${artifact.display} isn't valid UTF-8, so it can't be a ProGuard mapping.`
        )
    }
    throw new HogError(
        'invalid_proguard_mapping',
        `${artifact.display} is not a valid ProGuard mapping file.`,
        'Pass the mapping.txt that the Android build writes, usually under app/build/outputs/mapping/.'
    )
}

// hog-worker writes each symbol set to a file in a temporary folder, and hog reads a file when it
// sends it. A dry run writes nothing, so it has no folder.
export async function upload(
    ctx: Context,
    worker: Worker,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session = new Session(ctx),
    injected?: InjectedPairs
): Promise<UploadReport> {
    const folder = options.dryRun ? null : mkdtempSync(join(tmpdir(), CONTAINER_FOLDER_PREFIX))
    try {
        return await uploadFrom(ctx, worker, selection, options, session, injected, folder)
    } finally {
        if (folder !== null) {
            rmSync(folder, { recursive: true, force: true })
        }
    }
}

async function uploadFrom(
    ctx: Context,
    worker: Worker,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session,
    injected: InjectedPairs | undefined,
    folder: string | null
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
        for (const [index, artifact] of mappings.entries()) {
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
                    ...(await proguardUpload(
                        worker,
                        artifact,
                        folder === null ? null : join(folder, `mapping-${index}.${CONTAINER_EXTENSION}`)
                    )),
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
    const held = injected ? injected.pairs : await readPairs(worker, jsOnly, options, skipped)
    const pairs = held.filter(({ artifact }) => artifact.kind === 'js')
    await worker.drop(pairIds(held.filter(({ artifact }) => artifact.kind !== 'js')))
    let targets: number[] = []
    // posthog-cli stops before any cleanup when no bundle has an id to upload under.
    let jsUploadable = false
    const composed = selection.artifacts.filter(
        (artifact) => artifact.kind === 'hermes' && !isHermesBundlePath(artifact.path)
    )
    if (options.releaseMode === 'event' && options.skipOnConflict && (pairs.length > 0 || composed.length > 0)) {
        warnings.push(
            '--skip-on-conflict is ignored in event mode: every chunk is overwritten, so events never keep an old release.'
        )
    }
    if (pairs.length > 0) {
        const uploadable = pairs.filter(hasUploadId)
        jsUploadable = uploadable.length > 0
        if (!jsUploadable) {
            warnings.push(
                'No bundle has a chunk ID or a native debug ID, so there is nothing to upload. Run `hog error-tracking inject` first.'
            )
        }
        if (options.deleteAfter) {
            targets = await worker.fingerprint(pairIds(uploadable))
        }
        if (
            options.releaseMode === 'symbol-set' &&
            !injected?.release &&
            (releaseRequested(fields) || uploadable.some(withoutRelease))
        ) {
            const resolved = resolveJsRelease(fields, ctx.runtime.env, selection.cwd, warnings)
            if (resolved) {
                reported = { name: resolved.name, version: resolved.version, id: null }
                if (options.dryRun) {
                    warnings.push(DRY_RUN_RELEASE_WARNING)
                } else {
                    const release = await releases.get(resolved.name, resolved.version, resolved.git)
                    reported.id = release.id
                    await worker.setRelease(pairIds(uploadable), release.id)
                    for (const { pair } of uploadable) {
                        pair.mapReleaseId = release.id
                    }
                }
            }
        }
        if (
            options.releaseMode === 'symbol-set' &&
            (!options.dryRun || reported === null) &&
            uploadable.some(withoutRelease)
        ) {
            warnings.push(MISSING_RELEASE_WARNING)
        }
        const prepared = await preparePairs(worker, pairs, options.releaseMode, folder)
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
        for (const { owned, upload: item } of prepared.uploads) {
            planned.push({ artifact: owned.artifact, upload: item, policy })
        }
    }

    if (composed.length > 0) {
        if (options.releaseMode === 'event' && !(fields.name && fields.version && fields.build)) {
            warnings.push(
                'In event mode, exceptions take their release from the app. Pass --release-name, --release-version and --build matching the app identifier, version and build number, or exceptions will report no release.'
            )
        }
        const loaded = await worker.loadMaps(composed.map((artifact) => artifact.path))
        const maps = composed.map((artifact, index) => {
            const map = loaded[index]!
            if ('unreadable' in map) {
                throw new Error(map.unreadable)
            }
            return { artifact, map }
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
        const uploadable: { artifact: Artifact; map: MapState; chunkId: string }[] = []
        for (const { artifact, map } of maps) {
            const chunkId = uploadChunkId(map)
            if (chunkId === null) {
                skipped.push({
                    path: artifact.display,
                    reason: 'the map has no chunk ID. Run `hog error-tracking clone` after the Hermes build.',
                })
                continue
            }
            if (map.empty) {
                skipped.push({
                    path: artifact.display,
                    reason: 'the sourcemap is empty. Check your bundler sourcemap setting.',
                })
                continue
            }
            uploadable.push({ artifact, map, chunkId })
        }
        if (uploadable.length === 0) {
            throw new HogError(
                'no_hermes_chunk_ids',
                'None of the Hermes maps has a chunk ID, so nothing was uploaded.',
                'Run `hog error-tracking inject` on the Metro bundle before the Hermes build, and `hog error-tracking clone` after it.'
            )
        }

        const mapIds = uploadable.map(({ map }) => map.id)
        if (options.releaseMode === 'event') {
            await worker.setMapRelease(mapIds, null)
        } else if (releaseId !== null) {
            await worker.setMapRelease(mapIds, releaseId)
        }
        const containers = await worker.prepareMaps(mapIds, folder)

        for (const [index, { artifact, map, chunkId }] of uploadable.entries()) {
            const { path, ...container } = containers[index]!
            planned.push({
                artifact,
                upload: {
                    chunkId,
                    releaseId: options.releaseMode === 'event' ? null : (releaseId ?? map.releaseId),
                    ...container,
                    file: path,
                },
                policy,
            })
        }
    }

    const nativeArtifacts = selection.artifacts.filter(
        (artifact) => artifact.kind === 'elf' || artifact.kind === 'dsym'
    )
    if (nativeArtifacts.length > 0) {
        const before = skipped.length
        const native = await packageNative(
            worker,
            nativeArtifacts,
            selection.cwd,
            options.includeSource,
            folder,
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
        contentHash: item.upload.contentHash,
        size: item.upload.size,
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
        total_bytes: planned.reduce((sum, item) => sum + item.upload.size, 0),
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
        const ignored = (mapRealPath: string): boolean =>
            selection.roots.some((root, index) => isIgnored(root, realpathSync(rootPaths[index]!), mapRealPath))
        const stylesheets = await worker.cssCandidates(
            listFiles(selection.roots, selection.cwd).filter((path) => path.endsWith(CSS_EXTENSION)),
            options.publicPathPrefix
        )
        // A stylesheet whose reference can't be read has no map path, and the worker warns about it.
        const kept = stylesheets.filter(({ mapRealPath }) => mapRealPath === null || !ignored(mapRealPath))

        // Maps skipped as too large go too, as in posthog-cli, so they never ship with the build.
        const cleanup = await worker.cleanUp(
            targets,
            kept.map(({ id }) => id),
            rootPaths
        )
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
    worker: Worker,
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
        ? await injectPairs(ctx, worker, selection, options, session, preset, false)
        : undefined
    const report = await upload(ctx, worker, selection, options, session, injected)
    return { ...report, injected: injected?.injected ?? [] }
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

function readableMap(answer: MapAnswer, path: string, role: string): MapState {
    if ('unreadable' in answer) {
        throw new HogError('map_unreadable', `hog couldn't read the ${role} map ${path}: ${answer.unreadable}`)
    }
    return answer
}

export async function cloneMaps(
    ctx: Context,
    worker: Worker,
    fromPath: string,
    toPath: string,
    options: ErrorTrackingOptions
): Promise<CloneReport> {
    const cwd = ctx.runtime.cwd()
    const fromFile = resolve(cwd, fromPath)
    const answers = await worker.loadMaps([fromFile, resolve(cwd, toPath)])
    const from = readableMap(answers[0]!, fromPath, 'packager')
    const to = readableMap(answers[1]!, toPath, 'composed')

    const warnings: string[] = []
    let reported: ReleaseReport | null = null
    let releaseId: string | null = null
    if (options.releaseMode === 'symbol-set') {
        // Without release flags, the release `inject` stamped stays, and the upload binds to it.
        releaseId = from.releaseId
        const fields = await releaseFields(ctx, options)
        if (releaseRequested(fields) || from.releaseId === null) {
            const resolved = resolveJsRelease(fields, ctx.runtime.env, fromFile, warnings)
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

    const fromChanged = from.releaseId !== releaseId
    if (fromChanged) {
        await worker.setMapRelease([from.id], releaseId)
    }
    const cloned = await worker.cloneMetadata(from.id, to.id)
    if (!options.dryRun) {
        await worker.writeMaps(fromChanged ? [from.id, to.id] : [to.id])
    }

    return {
        dryRun: options.dryRun,
        release: reported,
        warnings,
        from: fromPath,
        to: toPath,
        chunkId: cloned.chunkId,
        releaseId: cloned.releaseId,
    }
}
