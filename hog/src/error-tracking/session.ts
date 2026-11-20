import { resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { Env } from '@/core/runtime'

import type { Artifact, Root } from './discover'
import { GitError, gitInfo, type GitInfo } from './git'
import { plistRelease } from './plist'
import { fetchOrCreateRelease, packVersion, type Release, type ReleaseFields } from './release'
import { SymbolSetClient, uuidv7 } from './upload'
import type { InjectAction } from './worker'

export type ReleaseMode = 'event' | 'symbol-set'

// `intended` marks a file hog left out on purpose, such as one an ignore pattern matches, so the upload
// still counts as complete.
export type Skip = { path: string; reason: string; intended?: true }

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

export const randomChunkId = (now: () => number) => (): string => uuidv7(now())

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
    }
    return name !== undefined && version !== undefined ? { name, version, git } : undefined
}

export function releaseRequested(fields: ReleaseFields): boolean {
    return fields.name !== undefined || fields.version !== undefined || fields.build !== undefined
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

export const DRY_RUN_RELEASE_WARNING =
    'PostHog assigns the release ID, so a dry run leaves it out. JavaScript content hashes from a dry run can differ from a real run.'
export const MISSING_RELEASE_WARNING =
    'No release could be resolved. Sourcemaps will upload without a release. Pass both --release-name and --release-version, or run from a git repository or supported CI environment.'
