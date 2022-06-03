#!/usr/bin/env node
import * as path from 'path'
import { startDevServer, buildInParallel, printResponse } from '../../utils.mjs'

import url from 'url'
export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))

startDevServer(__dirname)

await buildInParallel(
    [
        {
            name: 'Apps Common',
            absWorkingDir: __dirname,
            entryPoints: ['./src/index.ts'],
            bundle: true,
            format: 'esm',
            outfile: 'dist/index.js',
            chunkNames: '[name]',
            entryNames: '[dir]/[name]',
            external: ['react', 'react-dom'],
            publicPath: '',
        },
    ],
    {
        async onBuildComplete(config, response) {
            await printResponse(response, { verbose: false })
        },
    }
)
