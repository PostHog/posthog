import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { select, upload } from '@/error-tracking/run'

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
    description: 'Upload symbols so PostHog can show readable stack traces',
    args: PATHS,
    options: { ...SELECTION_OPTIONS, ...UPLOAD_OPTIONS, ...RELEASE_OPTIONS, ...DRY_RUN_OPTION },
    scopes: UPLOAD_SCOPES,
    notes: [
        "hog finds the artifacts in each path and detects their type from the files. A file it can't place, or one that two types could claim, is an error that names --kind.",
        'Supported: JavaScript bundles with sourcemaps, maps the Hermes compiler composed, ProGuard or R8 mappings (mapping.txt), dSYM bundles, and ELF or Mach-O files with debug info.',
        'JavaScript bundles need a chunk ID first: run `hog error-tracking inject`, or use `hog error-tracking process` to do both.',
    ].join('\n'),
    examples: [
        'hog error-tracking upload dist',
        'hog error-tracking upload app/build/outputs/mapping/release --map-id "$MAP_ID"',
        'hog et upload build/Build/Products/Release-iphoneos',
        'hog et upload --dry-run',
    ],

    async run({ args, options, ctx }) {
        const settings = await readOptions(options, ctx)
        const selection = await select(ctx, args.paths ?? [], settings)
        if (selection.artifacts.length === 0) {
            throw new HogError(
                'nothing_to_upload',
                'hog found no artifacts to upload in those paths.',
                'Check the paths, or pass --kind.'
            )
        }
        if (!settings.dryRun) {
            await ctx.ensureScopes(UPLOAD_SCOPES)
        }
        return upload(ctx, selection, settings)
    },

    human({ result, out }) {
        renderUpload(out, result)
    },
})
