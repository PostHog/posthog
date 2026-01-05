#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'
import fs from 'fs'
import { buildInParallel } from '@posthog/esbuilder'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

console.log('Building frontend for bundle analysis...')

await buildInParallel(
    [
        {
            name: 'PostHog App',
            globalName: 'posthogApp',
            entryPoints: ['src/index.tsx'],
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist-analysis'),
            absWorkingDir: __dirname,
            bundle: true,
        },
    ],
    {
        async onBuildComplete(_config, buildResponse) {
            if (buildResponse) {
                fs.writeFileSync(
                    path.resolve(__dirname, 'bundle-meta.json'),
                    JSON.stringify(buildResponse, null, 2)
                )
                console.log('Bundle metafile written to bundle-meta.json')

                // Clean up dist-analysis folder
                fs.rmSync(path.resolve(__dirname, 'dist-analysis'), { recursive: true, force: true })
            }
        },
    }
)

process.exit(0)
