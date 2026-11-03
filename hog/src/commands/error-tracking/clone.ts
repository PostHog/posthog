import { defineCommand } from '@/core/command'
import { cloneMaps } from '@/error-tracking/run'

import { DRY_RUN_OPTION, readOptions, RELEASE_OPTIONS, renderRelease } from './shared'

export default defineCommand({
    description: 'Copy the chunk ID and release from a Metro map to the map Hermes composed',
    args: {
        packagerMap: { description: "Metro's map of the bundle, after `hog error-tracking inject`" },
        composedMap: { description: 'The map the Hermes compiler composed for the bytecode' },
    },
    options: { ...RELEASE_OPTIONS, ...DRY_RUN_OPTION },
    scopes: ['error_tracking:write'],
    notes: [
        'React Native with Hermes takes three steps: inject the Metro bundle before the Hermes build, clone its chunk ID into the composed map after it, then upload the composed map.',
        'In event mode, clone needs no network. In symbol-set mode, it creates the release and stamps both maps with it.',
    ].join('\n'),
    examples: [
        'hog error-tracking clone index.android.bundle.map index.android.bundle.hbc.composed.map',
        'hog et clone main.jsbundle.map main.jsbundle.hbc.composed.map --release-mode symbol-set',
    ],

    async run({ args, options, ctx }) {
        return cloneMaps(ctx, args.packagerMap, args.composedMap, await readOptions(options, ctx))
    },

    human({ result, out }) {
        renderRelease(out, result.release)
        const what = result.chunkId ? `chunk ID ${out.style(result.chunkId, 'bold')}` : 'no chunk ID'
        out.line(`${result.dryRun ? 'Would copy' : 'Copied'} ${what} to ${result.to}.`)
    },
})
