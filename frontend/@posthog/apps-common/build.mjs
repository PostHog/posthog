#!/usr/bin/env node
import * as path from 'path'
import { startDevServer, buildInParallel, printResponse } from '../../utils.mjs'

import url from 'url'
export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))

startDevServer(__dirname)

const shared = {
    name: '@posthog/apps-common',
    absWorkingDir: __dirname,
    entryPoints: ['./src/index.ts'],
    bundle: true,
    chunkNames: '[name]',
    entryNames: '[dir]/[name]',
    external: ['react', 'react-dom'],
    publicPath: '',
    minify: false,
    target: 'esnext',
    sourcemap: false,
}

await buildInParallel(
    [
        {
            ...shared,
            name: `${shared.name} CJS`,
            format: 'cjs',
            outfile: 'dist/index.js',
        },
    ],
    {
        async onBuildComplete(config, response) {
            await printResponse(response, { verbose: false })
        },
    }
)
