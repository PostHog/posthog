#!/usr/bin/env node
import * as path from 'path'
import { __dirname, copyIndexHtml, copyPublicFolder, buildOrWatch, isDev, startServer } from './utils.mjs'

copyPublicFolder()
copyIndexHtml('src/index.html', 'dist/index.html', 'index')
copyIndexHtml('src/layout.html', 'dist/layout.html', 'index')
copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard')

let pauseServer = () => {}
let resumeServer = () => {}
if (isDev) {
    console.log(`👀 Starting dev server`)
    const serverResponse = startServer()
    pauseServer = serverResponse.pauseServer
    resumeServer = serverResponse.resumeServer
} else {
    console.log(`🛳 Starting production build`)
}

await Promise.all([
    buildOrWatch({
        name: 'PostHog App',
        entryPoints: ['src/index.tsx'],
        bundle: true,
        splitting: true,
        format: 'esm',
        outdir: path.resolve(__dirname, 'dist'),
        onBuildStart: pauseServer,
        onBuildComplete: resumeServer,
    }),
    buildOrWatch({
        name: 'Shared Dashboard',
        entryPoints: ['src/scenes/dashboard/SharedDashboard.tsx'],
        bundle: true,
        format: 'iife',
        outfile: path.resolve(__dirname, 'dist', 'shared_dashboard.js'),
        onBuildStart: pauseServer,
        onBuildComplete: resumeServer,
    }),
    buildOrWatch({
        name: 'Toolbar',
        entryPoints: ['src/toolbar/index.tsx'],
        bundle: true,
        format: 'iife',
        outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
        onBuildStart: pauseServer,
        onBuildComplete: resumeServer,
    }),
])
