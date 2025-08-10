#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'
import { buildInParallel } from '@posthog/esbuilder'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

await buildInParallel(
    [
        {
            entryPoints: ['src/index.ts'],
            bundle: true,
            outdir: 'dist',
            absWorkingDir: __dirname,
        },
    ],
    {
        async onBuildComplete() {
            console.info('Build complete')
        },
    }
)
