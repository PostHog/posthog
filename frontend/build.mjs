#!/usr/bin/env node
import * as path from 'path'
import {
    __dirname,
    copyPublicFolder,
    isDev,
    startServer,
    createHashlessEntrypoints,
    buildInParallel,
    copyIndexHtml,
} from './utils.mjs'

export function writeIndexHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/index.html', 'dist/index.html', 'index', chunks, entrypoints)
    copyIndexHtml('src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints)
}

export function writeSharedDashboardHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard', chunks, entrypoints)
}

let server
if (isDev) {
    console.log(`👀 Starting dev server`)
    server = startServer()
} else {
    console.log(`🛳 Starting production build`)
}
let buildsInProgress = 0

copyPublicFolder()
writeIndexHtml()
writeSharedDashboardHtml()

buildInParallel(
    [
        {
            name: 'PostHog App',
            entryPoints: ['src/index.tsx'],
            bundle: true,
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist'),
        },
        {
            name: 'Shared Dashboard',
            entryPoints: ['src/scenes/dashboard/SharedDashboard.tsx'],
            bundle: true,
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'shared_dashboard.js'),
        },
        {
            name: 'Toolbar',
            entryPoints: ['src/toolbar/index.tsx'],
            bundle: true,
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
        },
    ],
    {
        onBuildStart: () => {
            if (buildsInProgress === 0) {
                server?.pauseServer()
            }
            buildsInProgress++
        },
        onBuildComplete(config, buildResponse) {
            const { chunks, entrypoints } = buildResponse

            if (config.name === 'PostHog App') {
                if (Object.keys(chunks).length === 0) {
                    throw new Error('Could not get chunk metadata for bundle "PostHog App."')
                }
                if (Object.keys(entrypoints).length === 0) {
                    throw new Error('Could not get entrypoint for bundle "PostHog App."')
                }
                writeIndexHtml(chunks, entrypoints)
            }

            if (config.name === 'Shared Dashboard') {
                writeSharedDashboardHtml(chunks, entrypoints)
            }

            createHashlessEntrypoints(entrypoints)

            buildsInProgress--
            if (buildsInProgress === 0) {
                server?.resumeServer()
            }
        },
    }
)
