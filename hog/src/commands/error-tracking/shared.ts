import type { OptionSpec } from '@/core/command'
import { ARTIFACT_KINDS, type ArtifactKind } from '@/core/config'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Output } from '@/core/output'
import type { Env } from '@/core/runtime'
import { plural } from '@/core/text'
import type { ErrorTrackingOptions, InjectedReport, UploadReport } from '@/error-tracking/run'

// The options `inject`, `upload` and `process` share, and how their results look.

export const PATHS = {
    paths: {
        description: 'Files or folders to read. Defaults to errorTracking.sources in posthog.json',
        optional: true,
        variadic: true,
    },
} as const

export const SELECTION_OPTIONS = {
    kind: {
        type: 'string',
        choices: ARTIFACT_KINDS,
        description: 'The artifact type, when hog should not detect it',
    },
    publicPathPrefix: {
        type: 'string',
        placeholder: 'prefix',
        description: 'JavaScript only: the URL prefix to strip from sourceMappingURL comments to find maps on disk',
    },
} as const satisfies Record<string, OptionSpec>

export const RELEASE_OPTIONS = {
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
    releaseMode: {
        type: 'string',
        choices: ['event', 'symbol-set'],
        description: 'JavaScript only: put the release in the bundle (event, the default) or in the symbol set',
    },
} as const satisfies Record<string, OptionSpec>

export const UPLOAD_OPTIONS = {
    mapId: {
        type: 'string',
        placeholder: 'id',
        description: 'ProGuard only: the map ID your Android build injected into the app',
    },
    force: { type: 'boolean', description: 'Replace symbol sets PostHog already has with different content' },
    skipOnConflict: { type: 'boolean', description: 'Keep symbol sets PostHog already has with different content' },
    deleteAfter: {
        type: 'boolean',
        description: 'JavaScript and CSS: remove sourcemap references and delete the maps after a successful upload',
    },
    includeSource: {
        type: 'boolean',
        description:
            'dSYM and native files: bundle the source files their debug info names, and replace what PostHog has',
    },
    batchSize: {
        type: 'string',
        placeholder: 'count',
        description: 'Symbol sets per upload request (default 50, 10 for native symbols)',
    },
    concurrency: { type: 'string', placeholder: 'count', description: 'Parallel file uploads (default 10)' },
} as const satisfies Record<string, OptionSpec>

export const DRY_RUN_OPTION = {
    dryRun: {
        type: 'boolean',
        description: 'Show what would happen, with content hashes, without changing files or contacting PostHog',
    },
} as const satisfies Record<string, OptionSpec>

interface RawOptions {
    kind?: ArtifactKind
    publicPathPrefix?: string
    releaseName?: string
    releaseVersion?: string
    build?: string
    releaseMode?: 'event' | 'symbol-set'
    mapId?: string
    force?: boolean
    skipOnConflict?: boolean
    deleteAfter?: boolean
    includeSource?: boolean
    batchSize?: string
    concurrency?: string
    dryRun?: boolean
}

function count(flag: string, value: string | undefined, fallback: number): number {
    if (value === undefined) {
        return fallback
    }
    const parsed = Number(value)
    if (!Number.isInteger(parsed) || parsed < 1) {
        throw new HogError(
            'usage_error',
            `${flag} must be a whole number of at least 1.`,
            `Pass a number, as in ${flag} ${fallback}.`,
            EXIT_USAGE
        )
    }
    return parsed
}

// posthog-cli reads the release mode and the upload concurrency from these variables too.
export function readOptions(options: RawOptions, env: Env): ErrorTrackingOptions {
    if (options.force && options.skipOnConflict) {
        throw new HogError(
            'usage_error',
            '--force and --skip-on-conflict cannot be used together.',
            'Use --force to replace what PostHog has, or --skip-on-conflict to keep it.',
            EXIT_USAGE
        )
    }
    const releaseMode = options.releaseMode ?? env.POSTHOG_RELEASE_MODE ?? 'event'
    if (releaseMode !== 'event' && releaseMode !== 'symbol-set') {
        throw new HogError(
            'usage_error',
            'POSTHOG_RELEASE_MODE must be event or symbol-set.',
            'Unset it, or pass --release-mode.',
            EXIT_USAGE
        )
    }
    return {
        kind: options.kind,
        mapId: options.mapId,
        release: { name: options.releaseName, version: options.releaseVersion, build: options.build },
        releaseMode,
        publicPathPrefix: options.publicPathPrefix,
        force: options.force === true,
        skipOnConflict: options.skipOnConflict === true,
        batchSize: options.batchSize === undefined ? undefined : count('--batch-size', options.batchSize, 50),
        concurrency: count('--concurrency', options.concurrency ?? env.POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY, 10),
        deleteAfter: options.deleteAfter === true,
        includeSource: options.includeSource === true,
        dryRun: options.dryRun === true,
    }
}

export function renderRelease(out: Output, release: UploadReport['release']): void {
    if (release) {
        out.line(`Release ${out.style(`${release.name}@${release.version}`, 'bold')}`)
    }
}

export function renderNotes(out: Output, report: Pick<UploadReport, 'skipped' | 'warnings'>): void {
    for (const skip of report.skipped) {
        out.line(out.style(`Skipped ${skip.path}: ${skip.reason}`, 'yellow'))
    }
    for (const warning of report.warnings) {
        out.line(out.style(warning, 'yellow'))
    }
}

export function renderInjected(out: Output, injected: InjectedReport[]): void {
    out.table(
        [{ name: 'path' }, { name: 'chunk id' }, { name: 'action' }],
        injected.map((item) => [item.path, item.chunkId, item.action.replace('_', ' ')])
    )
}

export function renderUpload(out: Output, report: UploadReport): void {
    if (report.symbolSets.length > 0) {
        out.table(
            [
                { name: 'path' },
                { name: 'kind' },
                { name: 'chunk id' },
                { name: 'size', kind: 'number' },
                { name: 'status' },
            ],
            report.symbolSets.map((set) => [set.path, set.kind, set.chunkId, set.size, set.status.replace('_', ' ')])
        )
    }
    for (const path of report.deletedMaps) {
        out.line(out.style(`Deleted ${path}`, 'dim'))
    }
    renderNotes(out, report)
    const uploaded = report.symbolSets.filter((set) => set.status === 'uploaded').length
    const present = report.symbolSets.filter((set) => set.status === 'already_present').length
    const tooLarge = report.symbolSets.filter((set) => set.status === 'too_large').length
    out.line(
        out.style(
            report.dryRun
                ? `Dry run: ${plural(report.symbolSets.length, 'symbol set')} would be uploaded. Nothing was sent.`
                : `${plural(uploaded, 'symbol set')} uploaded, ${present} already present${tooLarge ? `, ${tooLarge} too large` : ''}.`,
            'dim'
        )
    )
}
