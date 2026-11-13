import type { OptionSpec } from '@/core/command'
import { ARTIFACT_KINDS, type ArtifactKind } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Output, Report } from '@/core/output'
import { plural } from '@/core/text'
import type { ErrorTrackingOptions, InjectedReport, UploadReport } from '@/error-tracking/run'

// The options `inject`, `upload` and `process` share, and how their results look.

export const UPLOAD_SCOPES = ['error_tracking:write']

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
    infoPlist: {
        type: 'string',
        placeholder: 'path',
        description: 'iOS: read the name, version and build the flags leave unset from this Info.plist',
    },
    releaseMode: {
        type: 'string',
        choices: ['event', 'symbol-set'],
        description:
            'JavaScript only: put the release in the bundle (event, the default) or in the symbol set. Defaults to HOG_RELEASE_MODE, then errorTracking.releaseMode in posthog.json',
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
    concurrency: {
        type: 'string',
        placeholder: 'count',
        description: 'Parallel file uploads (default HOG_UPLOAD_CONCURRENCY, then 10)',
    },
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
    infoPlist?: string
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

// The release mode comes from the flag, then HOG_RELEASE_MODE, then errorTracking.releaseMode in posthog.json.
export async function readOptions(options: RawOptions, ctx: Context): Promise<ErrorTrackingOptions> {
    const env = ctx.runtime.env
    if (options.force && options.skipOnConflict) {
        throw new HogError(
            'usage_error',
            '--force and --skip-on-conflict cannot be used together.',
            'Use --force to replace what PostHog has, or --skip-on-conflict to keep it.',
            EXIT_USAGE
        )
    }
    const releaseMode =
        options.releaseMode ??
        (env.HOG_RELEASE_MODE || undefined) ??
        (await ctx.config())?.config.errorTracking?.releaseMode ??
        'event'
    if (releaseMode !== 'event' && releaseMode !== 'symbol-set') {
        throw new HogError(
            'usage_error',
            'HOG_RELEASE_MODE must be event or symbol-set.',
            'Unset it, or pass --release-mode.',
            EXIT_USAGE
        )
    }
    return {
        kind: options.kind,
        mapId: options.mapId,
        release: { name: options.releaseName, version: options.releaseVersion, build: options.build },
        infoPlist: options.infoPlist,
        releaseMode,
        publicPathPrefix: options.publicPathPrefix,
        force: options.force === true,
        skipOnConflict: options.skipOnConflict === true,
        batchSize: options.batchSize === undefined ? undefined : count('--batch-size', options.batchSize, 50),
        concurrency: count('--concurrency', options.concurrency ?? env.HOG_UPLOAD_CONCURRENCY, 10),
        deleteAfter: options.deleteAfter === true,
        includeSource: options.includeSource === true,
        dryRun: options.dryRun === true,
    }
}

export function releaseLines(out: Output, release: UploadReport['release']): string[] {
    return release ? [`Release ${out.style(`${release.name}@${release.version}`, 'bold')}`] : []
}

export function warningLines(report: Pick<UploadReport, 'skipped' | 'warnings'>): string[] {
    return [...report.skipped.map((skip) => `Skipped ${skip.path}: ${skip.reason}`), ...report.warnings]
}

export function renderInjected(out: Output, injected: InjectedReport[]): void {
    out.table(
        [{ name: 'path' }, { name: 'chunk id' }, { name: 'action' }],
        injected.map((item) => [item.path, item.chunkId, item.action.replace('_', ' ')])
    )
}

function uploadResult(report: UploadReport): Pick<Report, 'status' | 'result'> {
    if (report.dryRun) {
        return {
            status: 'unchanged',
            result: `Dry run: ${plural(report.symbolSets.length, 'symbol set')} would be uploaded. Nothing was sent`,
        }
    }

    const uploaded = report.symbolSets.filter((set) => set.status === 'uploaded').length
    const present = report.symbolSets.filter((set) => set.status === 'already_present').length
    const tooLarge = report.symbolSets.filter((set) => set.status === 'too_large').length
    const unusable = report.skipped.filter((skip) => !skip.intended).length
    return {
        status: tooLarge > 0 || unusable > 0 ? 'partial' : uploaded === 0 ? 'unchanged' : 'done',
        result: `Uploaded ${plural(uploaded, 'symbol set')}, ${present} already present${tooLarge ? `, ${tooLarge} too large` : ''}${unusable ? `, ${unusable} skipped` : ''}`,
    }
}

// `effects` holds what the command did before the upload, such as injecting chunk IDs.
export function renderUpload(out: Output, report: UploadReport, effects: readonly string[] = []): void {
    out.report({
        ...uploadResult(report),
        effects: [
            ...releaseLines(out, report.release),
            ...effects,
            ...report.deletedMaps.map((path) => `Deleted ${path}`),
        ],
    })
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
    out.notes({ warnings: warningLines(report) })
}
