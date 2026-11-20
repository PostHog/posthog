import { realpathSync } from 'node:fs'
import { relative, resolve } from 'node:path'

import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'

import { isIgnored, type Artifact } from './discover'
import { randomChunkId, releaseRequested, resolveJsRelease } from './js-flow'
import { isHermesBundlePath } from './kinds/hermes'
import type { ReleaseMode, Skip } from './kinds/js'
import type { Release } from './release'
import {
    DRY_RUN_RELEASE_WARNING,
    MISSING_RELEASE_WARNING,
    releaseFields,
    Session,
    type ErrorTrackingOptions,
    type InjectedReport,
    type ReleaseReport,
    type Selection,
} from './run'
import type { SymbolSetFile } from './upload'
import type { InjectOutcome, PairState, Worker } from './worker'

export const isBundle = (artifact: Artifact): boolean =>
    artifact.kind === 'js' || (artifact.kind === 'hermes' && isHermesBundlePath(artifact.path))

export interface OwnedPair {
    pair: PairState
    artifact: Artifact
}

export async function readPairs(
    worker: Worker,
    selection: Selection,
    options: ErrorTrackingOptions,
    skipped: Skip[]
): Promise<OwnedPair[]> {
    const bundles = selection.artifacts.filter(isBundle)
    const answers = await worker.readPairs(
        bundles.map((artifact) => artifact.path),
        options.publicPathPrefix
    )

    const seen = new Set<string>()
    const pairs: OwnedPair[] = []
    const unused: number[] = []
    for (const [index, artifact] of bundles.entries()) {
        const answer = answers[index]
        if (!answer) {
            continue
        }
        if ('skipped' in answer) {
            skipped.push({ path: artifact.path, reason: answer.skipped })
            continue
        }

        if (isIgnored(artifact.root, realpathSync(resolve(selection.cwd, artifact.root.path)), answer.mapRealPath)) {
            skipped.push({
                path: artifact.display,
                reason: `its sourcemap matches an ignore pattern in posthog.json`,
                intended: true,
            })
            unused.push(answer.id)
            continue
        }

        if (seen.has(answer.sourcePath)) {
            unused.push(answer.id)
            continue
        }
        seen.add(answer.sourcePath)
        pairs.push({ pair: answer, artifact })
    }

    // The worker holds every pair it read, so the ones hog won't touch are let go.
    await worker.drop(unused)
    return pairs
}

export interface InjectedPairs {
    release: ReleaseReport | null
    injected: InjectedReport[]
    skipped: Skip[]
    warnings: string[]
    pairs: OwnedPair[]
}

const needsNewChunkId = (pair: PairState, releaseId: string | null): boolean =>
    pair.mapReleaseId !== releaseId || pair.chunkId === null

export async function injectPairs(
    ctx: Context,
    worker: Worker,
    selection: Selection,
    options: ErrorTrackingOptions,
    session: Session = new Session(ctx),
    preset?: Release,
    warnMissingRelease = true
): Promise<InjectedPairs> {
    const skipped: Skip[] = []
    const warnings: string[] = []
    const pairs = await readPairs(worker, selection, options, skipped)
    if (pairs.length === 0) {
        throw new HogError(
            'no_bundles',
            'hog found no JavaScript or Hermes bundles with sourcemaps to inject in those paths.',
            'Check the paths, or pass --public-path-prefix if your sourceMappingURL comments are absolute URLs.'
        )
    }

    // Hermes bundles never carry a release in event mode: the app's own metadata names it.
    const hermes = pairs.filter(({ artifact }) => artifact.kind === 'hermes')
    const js = pairs.filter(({ artifact }) => artifact.kind !== 'hermes')
    const fields = await releaseFields(ctx, options)
    let release = preset
    let reported: ReleaseReport | null = release
        ? { name: release.project, version: release.version, id: release.id }
        : null
    if (!release) {
        const needed =
            options.releaseMode === 'event'
                ? js.length > 0
                : releaseRequested(fields) || pairs.some(({ pair }) => pair.mapReleaseId === null)
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

    const ids = (owned: OwnedPair[]): number[] => owned.map(({ pair }) => pair.id)
    let outcomes: InjectOutcome[]
    if (options.releaseMode === 'event') {
        outcomes = [
            ...(await worker.inject(ids(js), 'event', releaseId)),
            ...(await worker.inject(ids(hermes), 'event', null)),
        ]
    } else {
        const newChunkId = randomChunkId(ctx.runtime.now)
        const newChunkIds = pairs.filter(({ pair }) => needsNewChunkId(pair, releaseId)).map(newChunkId)
        outcomes = await worker.inject(ids(pairs), 'symbol-set', releaseId, newChunkIds)
    }
    const byId = new Map(outcomes.map((outcome) => [outcome.pair.id, outcome]))
    for (const outcome of outcomes) {
        warnings.push(...outcome.warnings)
    }
    const injected = pairs.map(({ pair, artifact }) => ({ pair: byId.get(pair.id)!.pair, artifact }))

    if (
        warnMissingRelease &&
        options.releaseMode === 'symbol-set' &&
        reported === null &&
        injected.some(({ pair }) => pair.mapReleaseId === null)
    ) {
        warnings.push(MISSING_RELEASE_WARNING)
    }
    if (!options.dryRun) {
        await worker.save(ids(injected))
    }

    const cwd = realpathSync(selection.cwd)
    return {
        release: reported,
        injected: injected.map(({ pair, artifact }) => {
            const outcome = byId.get(pair.id)!
            return {
                path: artifact.display,
                map: relative(cwd, pair.mapPath),
                chunkId: outcome.chunkId,
                action: outcome.action,
            }
        }),
        skipped,
        warnings,
        pairs: injected,
    }
}

export interface PreparedPairs {
    uploads: { owned: OwnedPair; upload: SymbolSetFile }[]
    skipped: Skip[]
    duplicates: string[]
}

// A bundle with a native debug id and no chunk id carries the id its map is known by, so it goes
// first and wins when a second pair has the same id.
const nativeFirst = ({ pair }: OwnedPair): number => (pair.chunkId === null && pair.sourceDebugId !== null ? 0 : 1)

// One symbol set per chunk id, written by the worker into `folder`. A dry run passes no folder
// and gets the sizes and content hashes only.
export async function preparePairs(
    worker: Worker,
    pairs: OwnedPair[],
    mode: ReleaseMode,
    folder: string | null
): Promise<PreparedPairs> {
    const prepared = await worker.prepare(
        pairs.map(({ pair }) => pair.id),
        mode,
        folder
    )

    const skipped: Skip[] = []
    const uploads: PreparedPairs['uploads'] = []
    for (const [index, owned] of pairs.entries()) {
        const answer = prepared[index]!
        if ('skipped' in answer) {
            skipped.push({ path: owned.pair.sourcePath, reason: answer.skipped })
            continue
        }
        const { path, ...container } = answer
        uploads.push({ owned, upload: { ...container, file: path } })
    }

    const sorted = uploads
        .map((entry, index) => ({ entry, index }))
        .sort((a, b) => nativeFirst(a.entry.owned) - nativeFirst(b.entry.owned) || a.index - b.index)
    const seen = new Set<string>()
    const duplicates: string[] = []
    const kept = sorted
        .map(({ entry }) => entry)
        .filter((entry) => {
            if (seen.has(entry.upload.chunkId)) {
                duplicates.push(entry.upload.chunkId)
                return false
            }
            seen.add(entry.upload.chunkId)
            return true
        })

    return { uploads: kept, skipped, duplicates }
}
