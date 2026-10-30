import { randomUUID } from 'node:crypto'
import {
    accessSync,
    chmodSync,
    constants,
    readFileSync,
    realpathSync,
    renameSync,
    rmSync,
    statSync,
    writeFileSync,
} from 'node:fs'

import { HogError } from '@/core/errors'
import type { Env } from '@/core/runtime'

import { GitError, gitInfo, type GitInfo } from './git'
import { isEmptyMapContent, isUuid, pairUpload, uuidv5, type ReleaseMode, type Skip, type SourcePair } from './kinds/js'
import { packVersion, type ReleaseFields } from './release'
import { uuidv7, type SymbolSetUpload } from './upload'

export type InjectAction = 'injected' | 'release_updated' | 'unchanged'

export interface InjectOutcome {
    pair: SourcePair
    action: InjectAction
    chunkId: string
}

// A bundler debug id becomes the chunk id when it parses as a UUID. The source comment wins over the
// map's `debugId` when both exist.
function adoptedDebugId(pair: SourcePair, warnings: string[]): string | null {
    const id = pair.debugId()
    if (id === null) {
        return null
    }
    const fromMap = pair.map.debugId
    if (pair.sourceDebugId() !== null && fromMap !== null && fromMap !== pair.sourceDebugId()) {
        warnings.push(`${pair.sourcePath}: the chunk and its sourcemap have different debug ids. Using the chunk's.`)
    }
    if (isUuid(id)) {
        return id
    }
    warnings.push(
        `${pair.sourcePath}: ignoring the malformed debug id ${JSON.stringify(id)} and deriving a chunk id from the content.`
    )
    return null
}

// Event mode: chunk ids derive from the bundle's content (UUIDv5), so they stay stable across
// rebuilds. A resolved release goes into the snippet; a changed release swaps only the snippet.
export function injectEventMode(pairs: SourcePair[], releaseId: string | null, warnings: string[]): InjectOutcome[] {
    return pairs.map((pair) => {
        const existing = pair.chunkId()
        if (existing === null) {
            const chunkId = adoptedDebugId(pair, warnings) ?? uuidv5(Buffer.from(pair.source, 'utf8'))
            pair.addChunkId(chunkId, releaseId)
            return { pair, action: 'injected', chunkId }
        }
        if (releaseId === null || pair.injectedReleaseId() === releaseId) {
            return { pair, action: 'unchanged', chunkId: existing }
        }
        pair.removeChunkId(existing)
        pair.addChunkId(existing, releaseId)
        return { pair, action: 'release_updated', chunkId: existing }
    })
}

export function injectSymbolSetMode(
    pairs: SourcePair[],
    releaseId: string | null,
    newId: () => string
): InjectOutcome[] {
    return pairs.map((pair) => {
        const existing = pair.chunkId()
        if (pair.map.releaseId === releaseId && existing !== null) {
            return { pair, action: 'unchanged', chunkId: existing }
        }
        pair.map.releaseId = releaseId
        const chunkId = newId()
        if (existing !== null) {
            pair.removeChunkId(existing)
        }
        pair.addChunkId(chunkId, null)
        return { pair, action: existing === null ? 'injected' : 'release_updated', chunkId }
    })
}

export const randomChunkId = (now: () => number) => (): string => uuidv7(now())

// posthog-cli writes every pair only after all of them were transformed, so a failure leaves the
// build untouched. Unchanged pairs are written too, which puts every map in canonical form.
export function savePairs(pairs: SourcePair[], serialize: (pair: SourcePair) => string): void {
    replaceFiles(
        pairs.flatMap((pair): [string, string][] => [
            [pair.sourcePath, pair.source],
            [pair.mapPath, serialize(pair)],
        ])
    )
}

// Writes every file next to its target first, then renames them all into place. A full disk or a
// read-only target then fails before any target changes, instead of leaving a bundle injected
// while its map keeps the old offsets, which a rerun can't repair. A rename can still fail, for
// example on a file another Windows process holds open, so the files already replaced get their
// old contents back.
function replaceFiles(files: [string, string][]): void {
    const staged: { temporary: string; target: string; original: Buffer }[] = []
    let renamed = 0
    try {
        for (const [path, contents] of files) {
            const target = realpathSync(path)
            // A rename would replace a read-only file, where posthog-cli's write fails.
            accessSync(target, constants.W_OK)
            const temporary = `${target}.${randomUUID()}.tmp`
            staged.push({ temporary, target, original: readFileSync(target) })
            writeFileSync(temporary, contents, { flag: 'wx' })
            chmodSync(temporary, statSync(target).mode & 0o7777)
        }
        for (const { temporary, target } of staged) {
            renameSync(temporary, target)
            renamed++
        }
    } catch (error) {
        for (const { target, original } of staged.slice(0, renamed)) {
            writeFileSync(target, original)
        }
        for (const { temporary } of staged.slice(renamed)) {
            rmSync(temporary, { force: true })
        }
        throw error
    }
}

export interface PreparedPairs {
    uploads: { pair: SourcePair; upload: SymbolSetUpload }[]
    skipped: Skip[]
    duplicates: string[]
}

export function preparePairs(pairs: SourcePair[], mode: ReleaseMode): PreparedPairs {
    const skipped: Skip[] = []
    const uploads: { pair: SourcePair; upload: SymbolSetUpload }[] = []
    for (const pair of pairs) {
        if (pair.chunkId() === null && pair.debugId() === null) {
            skipped.push({
                path: pair.sourcePath,
                reason: 'no PostHog chunk ID or native debug ID. Run `hog error-tracking inject` first.',
            })
            continue
        }
        if (isEmptyMapContent(pair.map)) {
            skipped.push({
                path: pair.sourcePath,
                reason:
                    Buffer.byteLength(pair.source) < 2048
                        ? 'the sourcemap is empty'
                        : 'the sourcemap is empty although the file is large. Check your bundler sourcemap setting.',
            })
            continue
        }
        uploads.push({ pair, upload: pairUpload(pair, mode) })
    }
    const nativeFirst = (entry: { pair: SourcePair }): number =>
        entry.pair.chunkId() === null && entry.pair.sourceDebugId() !== null ? 0 : 1
    const sorted = uploads
        .map((entry, index) => ({ entry, index }))
        .sort((a, b) => nativeFirst(a.entry) - nativeFirst(b.entry) || a.index - b.index)
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

export interface JsRelease {
    name: string
    version: string
    git: GitInfo | undefined
}

export function resolveJsRelease(
    fields: ReleaseFields,
    env: Env,
    cwd: string,
    warnings: string[]
): JsRelease | undefined {
    let name = fields.name
    let version = packVersion(fields.version, fields.build)
    const complete = name !== undefined && version !== undefined
    let git: GitInfo | undefined
    try {
        git = gitInfo(env, cwd)
    } catch (error) {
        if (!(error instanceof GitError)) {
            throw error
        }
        if (!complete) {
            throw new HogError(
                'git_failed',
                `hog couldn't read the git repository for the release: ${error.message}`,
                'Pass --release-name and --release-version.'
            )
        }
        warnings.push(`Skipping git metadata for the release: ${error.message}`)
    }
    if (git) {
        name ??= git.repo_name
        version ??= git.commit_id
    } else if (!complete && (fields.name !== undefined || fields.version !== undefined || fields.build !== undefined)) {
        throw new HogError(
            'release_incomplete',
            'The release needs both a name and a version, and there is no git repository to fill in the missing one.',
            'Pass both --release-name and --release-version, or run from a git repository.'
        )
    }
    return name !== undefined && version !== undefined ? { name, version, git } : undefined
}

export function releaseRequested(fields: ReleaseFields): boolean {
    return fields.name !== undefined || fields.version !== undefined || fields.build !== undefined
}
