#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'
import { buildInParallel } from '@posthog/esbuilder'
import { BUILD_DIST_FOLDER } from '../esbuilder/utils.mjs'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

await buildInParallel([
    {
        entryPoints: ['src/index.ts'],
        bundle: true,
        outdir: BUILD_DIST_FOLDER,
        absWorkingDir: __dirname,
    }
], {
    async onBuildComplete(config, buildResponse) {
        console.log('Build complete')
    }
})
