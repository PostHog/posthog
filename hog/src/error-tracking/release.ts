import { HogError } from '@/core/errors'

import { contentHash } from './container'
import type { GitInfo } from './git'
import { ApiFailure, type SymbolSetClient } from './upload'

export interface Release {
    id: string
    hash_id: string
    version: string
    project: string
}

export interface ReleaseFields {
    name?: string
    version?: string
    build?: string
}

// posthog-cli's `pack_version`: `version+build`, or whichever of the two is set.
export function packVersion(version: string | undefined, build: string | undefined): string | undefined {
    if (version !== undefined && build !== undefined) {
        return `${version}+${build}`
    }
    return version ?? build
}

// The release's identity on the server. Symbolication recomputes it for mobile releases, so it must
// stay exactly SHA-512 of the name followed by the version, with nothing between them.
export function releaseHashId(name: string, version: string): string {
    return contentHash(name, version)
}

export function resolveRelease(fields: ReleaseFields, git: GitInfo | undefined): { name?: string; version?: string } {
    return {
        name: fields.name ?? git?.repo_name,
        version: packVersion(fields.version, fields.build) ?? git?.commit_id,
    }
}

// serde_json turns the git info into a map with sorted keys before it is sent.
function gitMetadata(git: GitInfo): Record<string, string> {
    return Object.fromEntries(
        Object.entries(git)
            .filter(([, value]) => value !== undefined)
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    )
}

// Looks the release up without creating it, for a dry run.
export async function findRelease(
    client: SymbolSetClient,
    name: string,
    version: string
): Promise<Release | undefined> {
    const existing = await lookup(client, releaseHashId(name, version))
    return existing && { ...existing, id: existing.id.toLowerCase() }
}

async function lookup(client: SymbolSetClient, hashId: string): Promise<Release | undefined> {
    try {
        return (await client.api('GET', `error_tracking/releases/hash/${hashId}`)) as Release
    } catch (error) {
        if (error instanceof ApiFailure && error.status === 404) {
            return undefined
        }
        throw new HogError('release_lookup_failed', `hog couldn't look up the release: ${(error as Error).message}`)
    }
}

// Finds the release by its hash id, or creates it. Two builds racing to create the same release is
// fine: the loser looks it up again.
export async function fetchOrCreateRelease(
    client: SymbolSetClient,
    name: string,
    version: string,
    metadata: { git?: GitInfo; dsym_info?: Record<string, string | null> } = {}
): Promise<Release> {
    const hashId = releaseHashId(name, version)
    const existing = await lookup(client, hashId)
    if (existing) {
        return { ...existing, id: existing.id.toLowerCase() }
    }
    const body: Record<string, unknown> = {}
    const meta: Record<string, unknown> = {}
    if (metadata.git) {
        meta.git = gitMetadata(metadata.git)
    }
    if (metadata.dsym_info) {
        meta.dsym_info = metadata.dsym_info
    }
    if (Object.keys(meta).length > 0) {
        body.metadata = meta
    }
    Object.assign(body, { hash_id: hashId, version, project: name })
    try {
        const created = (await client.api('POST', 'error_tracking/releases', body)) as Release
        return { ...created, id: created.id.toLowerCase() }
    } catch (error) {
        if (error instanceof ApiFailure && isStructuredCode(error.body, 'release_hash_in_use')) {
            const raced = await lookup(client, hashId)
            if (raced) {
                return { ...raced, id: raced.id.toLowerCase() }
            }
        }
        throw new HogError('release_create_failed', `hog couldn't create the release: ${(error as Error).message}`)
    }
}

function isStructuredCode(body: string, code: string): boolean {
    try {
        return (JSON.parse(body) as { code?: unknown }).code === code
    } catch {
        return false
    }
}
