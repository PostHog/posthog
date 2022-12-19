#!/usr/bin/env node
import * as path from 'path'
import * as fs from 'fs'
import { startDevServer, buildInParallel, printResponse } from '../../utils.mjs'
import url from 'url'

export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const { name, peerDependencies } = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json')))

startDevServer(__dirname)

await buildInParallel(
    [
        {
            name,
            absWorkingDir: __dirname,
            entryPoints: ['./src/index.ts'],
            format: 'cjs',
            outfile: 'dist/index.js',
            bundle: true,
            chunkNames: '[name]',
            entryNames: '[dir]/[name]',
            external: Object.keys(peerDependencies ?? []),
            publicPath: '',
            minify: true,
            target: 'esnext',
            sourcemap: false,
        },
    ],
    {
        async onBuildComplete(config, response) {
            await printResponse(response, { verbose: true, compact: false })
        },
    }
)
