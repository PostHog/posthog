import { defineCommand } from '@/core/command'
import { plural } from '@/core/text'
import { inject, select } from '@/error-tracking/run'

import {
    DRY_RUN_OPTION,
    PATHS,
    readOptions,
    RELEASE_OPTIONS,
    renderInjected,
    renderNotes,
    renderRelease,
} from './shared'

export default defineCommand({
    description: 'Add chunk IDs to JavaScript bundles and their sourcemaps',
    args: PATHS,
    options: {
        publicPathPrefix: {
            type: 'string',
            placeholder: 'prefix',
            description: 'The URL prefix to strip from sourceMappingURL comments to find maps on disk',
        },
        ...RELEASE_OPTIONS,
        ...DRY_RUN_OPTION,
    },
    scopes: ['error_tracking:write'],
    notes: [
        'Each bundle gets a snippet that registers its chunk ID at runtime, and its sourcemap gets the same ID, so PostHog can match stack frames to the right map.',
        'Chunk IDs come from the bundle content, so the same build gets the same IDs. Running inject again changes nothing unless the release changed.',
        'In event mode the release comes from the flags, posthog.json or git, and PostHog creates it, which needs credentials.',
    ].join('\n'),
    examples: ['hog error-tracking inject dist', 'hog et inject dist --release-name web --release-version 1.4.0'],

    async run({ args, options, ctx }) {
        const settings = await readOptions(options, ctx)
        const selection = await select(ctx, args.paths ?? [], settings)
        const report = await inject(ctx, selection, settings)
        return {
            dryRun: settings.dryRun,
            release: report.release,
            injected: report.injected,
            skipped: report.skipped,
            warnings: report.warnings,
        }
    },

    human({ result, out }) {
        renderRelease(out, result.release)
        renderInjected(out, result.injected)
        renderNotes(out, result)
        const changed = result.injected.filter((item) => item.action !== 'unchanged').length
        out.line(
            out.style(
                result.dryRun
                    ? `Dry run: ${changed} of ${plural(result.injected.length, 'bundle')} would change. No file was written.`
                    : `${changed} of ${plural(result.injected.length, 'bundle')} changed.`,
                'dim'
            )
        )
    },
})
