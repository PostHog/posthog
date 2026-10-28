import { realpathSync } from 'node:fs'
import { dirname } from 'node:path'

import { defineCommand } from '@/core/command'
import { ARTIFACT_KINDS } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { plural } from '@/core/text'
import { contentHash } from '@/error-tracking/container'
import { discover, type Artifact, type Root } from '@/error-tracking/discover'
import { GitError, gitInfo, type GitInfo } from '@/error-tracking/git'
import { proguardContainer } from '@/error-tracking/kinds/proguard'
import { fetchOrCreateRelease, resolveRelease, type Release } from '@/error-tracking/release'
import { SymbolSetClient, type SymbolSetUpload, type UploadStatus } from '@/error-tracking/upload'

interface PlannedSymbolSet {
    path: string
    kind: string
    chunkId: string
    contentHash: string
    size: number
    status: UploadStatus | 'planned'
}

interface UploadResult {
    dryRun: boolean
    release: { name: string; version: string; id: string | null } | null
    symbolSets: PlannedSymbolSet[]
}

interface Prepared {
    artifact: Artifact
    upload: SymbolSetUpload
}

function prepare(artifact: Artifact, mapId: string | undefined): Prepared {
    // ProGuard mappings carry no id of their own: the Android build plugin writes one into the app,
    // and the same value must be passed here.
    const chunkId = mapId ?? artifact.root.mapId
    if (!chunkId) {
        throw new HogError(
            'map_id_required',
            `${artifact.display} is a ProGuard mapping, which needs the map ID your build injected into the app.`,
            'Pass --map-id, or set "mapId" on the source in posthog.json.',
            EXIT_USAGE
        )
    }
    return { artifact, upload: { chunkId, releaseId: null, data: proguardContainer(artifact.path, artifact.display) } }
}

async function roots(
    ctx: Context,
    paths: string[],
    kind: Root['kind'],
    mapId: string | undefined
): Promise<{ roots: Root[]; cwd: string }> {
    if (paths.length > 0) {
        return { roots: paths.map((path) => ({ path, kind, mapId })), cwd: ctx.runtime.cwd() }
    }
    const loaded = await ctx.config()
    const sources = loaded?.config.errorTracking?.sources ?? []
    if (!loaded || sources.length === 0) {
        throw new HogError(
            'no_paths',
            'Pass the files or folders to upload, or list them under errorTracking.sources in posthog.json.',
            'Run `hog config schema` to see the posthog.json format.',
            EXIT_USAGE
        )
    }
    return { roots: sources.map((source) => ({ ...source, kind: kind ?? source.kind })), cwd: loaded.root }
}

function releaseGit(ctx: Context, artifacts: Artifact[]): GitInfo | undefined {
    const first = artifacts[0]
    if (!first) {
        return undefined
    }
    try {
        // posthog-cli resolves symlinks first, so a link outside the repository still finds it.
        return gitInfo(ctx.runtime.env, dirname(realpathSync(first.path)))
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

export default defineCommand({
    description: 'Upload symbols so PostHog can show readable stack traces',
    args: {
        paths: {
            description: 'Files or folders to upload. Defaults to errorTracking.sources in posthog.json',
            optional: true,
            variadic: true,
        },
    },
    options: {
        kind: {
            type: 'string',
            choices: ARTIFACT_KINDS,
            description: 'The artifact type, when hog should not detect it',
        },
        mapId: {
            type: 'string',
            placeholder: 'id',
            description: 'ProGuard only: the map ID your Android build injected into the app',
        },
        releaseName: {
            type: 'string',
            placeholder: 'name',
            description: 'The release name. Defaults to the git repository name',
        },
        releaseVersion: {
            type: 'string',
            placeholder: 'version',
            description: 'The release version. Defaults to the git commit',
        },
        build: {
            type: 'string',
            placeholder: 'build',
            description: 'A build number, added to the version as version+build',
        },
        force: { type: 'boolean', description: 'Replace symbol sets PostHog already has with different content' },
        skipOnConflict: { type: 'boolean', description: 'Keep symbol sets PostHog already has with different content' },
        batchSize: { type: 'string', placeholder: 'count', description: 'Symbol sets per upload request (default 50)' },
        dryRun: {
            type: 'boolean',
            description: 'Show what would be uploaded, with content hashes, without contacting PostHog',
        },
    },
    scopes: ['error_tracking:write'],
    notes: [
        "hog finds the artifacts in each path and detects their type from the files. A file it can't place, or one that two types could claim, is an error that names --kind.",
        'Supported: ProGuard and R8 mappings (mapping.txt).',
    ].join('\n'),
    examples: [
        'hog error-tracking upload app/build/outputs/mapping/release --map-id "$MAP_ID"',
        'hog et upload --dry-run',
    ],

    async run({ args, options, ctx }): Promise<UploadResult> {
        if (options.force && options.skipOnConflict) {
            throw new HogError(
                'usage_error',
                '--force and --skip-on-conflict cannot be used together.',
                undefined,
                EXIT_USAGE
            )
        }
        const batchSize = options.batchSize === undefined ? 50 : Number(options.batchSize)
        if (!Number.isInteger(batchSize) || batchSize < 1) {
            throw new HogError(
                'usage_error',
                '--batch-size must be a whole number of at least 1.',
                undefined,
                EXIT_USAGE
            )
        }
        const { roots: found, cwd } = await roots(ctx, args.paths ?? [], options.kind, options.mapId)
        const artifacts = discover(found, cwd)
        if (artifacts.length === 0) {
            throw new HogError(
                'nothing_to_upload',
                'hog found no artifacts to upload in those paths.',
                'Check the paths, or pass --kind.'
            )
        }
        const prepared = artifacts.map((artifact) => prepare(artifact, options.mapId))
        const duplicate = prepared.find(
            (item, index) => prepared.findIndex((other) => other.upload.chunkId === item.upload.chunkId) !== index
        )
        if (duplicate) {
            throw new HogError(
                'duplicate_chunk_id',
                `Two artifacts share the chunk ID ${duplicate.upload.chunkId}.`,
                'Give each mapping its own --map-id.'
            )
        }

        const config = (await ctx.config())?.config.errorTracking?.release
        const git = releaseGit(ctx, artifacts)
        const { name, version } = resolveRelease(
            {
                name: options.releaseName ?? config?.name,
                version: options.releaseVersion ?? config?.version,
                build: options.build,
            },
            git
        )

        const describe = (item: Prepared, status: PlannedSymbolSet['status']): PlannedSymbolSet => ({
            path: item.artifact.display,
            kind: item.artifact.kind,
            chunkId: item.upload.chunkId,
            contentHash: item.upload.contentHash ?? contentHash(item.upload.data),
            size: item.upload.data.length,
            status,
        })
        const release = name !== undefined && version !== undefined ? { name, version } : undefined
        if (options.dryRun) {
            return {
                dryRun: true,
                release: release ? { ...release, id: null } : null,
                symbolSets: prepared.map((item) => describe(item, 'planned')),
            }
        }

        const client = new SymbolSetClient(ctx.runtime, await ctx.credentials())
        let created: Release | undefined
        if (release) {
            created = await fetchOrCreateRelease(client, release.name, release.version, git ? { git } : {})
        }
        const uploads = prepared.map((item) => ({ ...item.upload, releaseId: created?.id ?? null }))
        const outcome = await client.upload(uploads, {
            batchSize,
            force: options.force === true,
            skipOnConflict: options.skipOnConflict === true,
        })
        return {
            dryRun: false,
            release: release ? { ...release, id: created?.id ?? null } : null,
            symbolSets: prepared.map((item) =>
                describe(item, outcome.status.get(item.upload.chunkId) ?? 'already_present')
            ),
        }
    },

    human({ result, out }) {
        if (result.release) {
            out.line(`Release ${out.style(`${result.release.name}@${result.release.version}`, 'bold')}`)
        }
        out.table(
            [
                { name: 'path' },
                { name: 'kind' },
                { name: 'chunk id' },
                { name: 'size', kind: 'number' },
                { name: 'status' },
            ],
            result.symbolSets.map((set) => [set.path, set.kind, set.chunkId, set.size, set.status.replace('_', ' ')])
        )
        const uploaded = result.symbolSets.filter((set) => set.status === 'uploaded').length
        const present = result.symbolSets.filter((set) => set.status === 'already_present').length
        const tooLarge = result.symbolSets.filter((set) => set.status === 'too_large').length
        out.line(
            out.style(
                result.dryRun
                    ? `Dry run: ${plural(result.symbolSets.length, 'symbol set')} would be uploaded. Nothing was sent.`
                    : `${plural(uploaded, 'symbol set')} uploaded, ${present} already present${tooLarge ? `, ${tooLarge} too large` : ''}.`,
                'dim'
            )
        )
    },
})
