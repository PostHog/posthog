import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { plural } from '@/core/text'
import { processArtifacts, select } from '@/error-tracking/run'

import {
    DRY_RUN_OPTION,
    PATHS,
    readOptions,
    RELEASE_OPTIONS,
    renderUpload,
    SELECTION_OPTIONS,
    UPLOAD_OPTIONS,
    UPLOAD_SCOPES,
} from './shared'

export default defineCommand({
    description: 'Inject chunk IDs into JavaScript bundles, then upload every artifact',
    args: PATHS,
    options: { ...SELECTION_OPTIONS, ...UPLOAD_OPTIONS, ...RELEASE_OPTIONS, ...DRY_RUN_OPTION },
    scopes: UPLOAD_SCOPES,
    notes: [
        'Runs `hog error-tracking inject` on the JavaScript bundles, then `hog error-tracking upload` on everything it found. Use it in CI after the build.',
        'When --release-name, --release-version or --build is set, PostHog creates the release before any file changes.',
    ].join('\n'),
    examples: ['hog error-tracking process dist', 'hog et process dist --delete-after'],

    async run({ args, options, ctx }) {
        const settings = await readOptions(options, ctx)
        const selection = await select(ctx, args.paths ?? [], settings)
        if (selection.artifacts.length === 0) {
            throw new HogError(
                'nothing_to_upload',
                'hog found no artifacts to process in those paths.',
                'Check the paths, or pass --kind.'
            )
        }
        if (!settings.dryRun) {
            await ctx.ensureScopes(UPLOAD_SCOPES)
        }
        return processArtifacts(ctx, selection, settings)
    },

    human({ result, out }) {
        const changed = result.injected.filter((item) => item.action !== 'unchanged').length
        const already = result.injected.length - changed
        renderUpload(
            out,
            result,
            result.injected.length > 0
                ? [
                      `Injected chunk IDs into ${plural(changed, 'bundle')}${already > 0 ? `, ${already} already had them` : ''}`,
                  ]
                : []
        )
    },
})
