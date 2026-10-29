import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { plural } from '@/core/text'
import { processArtifacts, select } from '@/error-tracking/run'

import {
    DRY_RUN_OPTION,
    PATHS,
    readOptions,
    RELEASE_OPTIONS,
    renderRelease,
    renderUpload,
    SELECTION_OPTIONS,
    UPLOAD_OPTIONS,
} from './shared'

export default defineCommand({
    description: 'Inject chunk IDs into JavaScript bundles, then upload every artifact',
    args: PATHS,
    options: { ...SELECTION_OPTIONS, ...UPLOAD_OPTIONS, ...RELEASE_OPTIONS, ...DRY_RUN_OPTION },
    scopes: ['error_tracking:write'],
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
        return processArtifacts(ctx, selection, settings)
    },

    human({ result, out }) {
        renderRelease(out, result.release)
        if (result.injected.length > 0) {
            const changed = result.injected.filter((item) => item.action !== 'unchanged').length
            out.line(
                `Injected chunk IDs into ${plural(changed, 'bundle')}${changed < result.injected.length ? `, ${result.injected.length - changed} already had them` : ''}.`
            )
        }
        renderUpload(out, result)
    },
})
