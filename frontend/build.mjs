#!/usr/bin/env node
import * as path from 'path'
import { __dirname, copyIndexHtml, copyPublicFolder, buildOrWatch, isDev, startServer } from './utils.mjs'

function writeIndexHtml(chunks = {}) {
    copyIndexHtml('src/index.html', 'dist/index.html', 'index', chunks)
    copyIndexHtml('src/layout.html', 'dist/layout.html', 'index', chunks)
    copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard', chunks)
}

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
let buildsInProgress = 0
function onBuildStart() {
    if (buildsInProgress === 0) {
        pauseServer()
    }
    buildsInProgress++
}
function onBuildComplete(chunks) {
    buildsInProgress--
    if (buildsInProgress === 0) {
        resumeServer()
        writeIndexHtml(chunks)
    }
}

copyPublicFolder()
writeIndexHtml({})

await Promise.all([
    buildOrWatch({
        name: 'PostHog App',
        entryPoints: ['src/index.tsx'],
        bundle: true,
        splitting: true,
        format: 'esm',
        outdir: path.resolve(__dirname, 'dist'),
        onBuildStart,
        onBuildComplete,
    }),
    buildOrWatch({
        name: 'Shared Dashboard',
        entryPoints: ['src/scenes/dashboard/SharedDashboard.tsx'],
        bundle: true,
        format: 'iife',
        outfile: path.resolve(__dirname, 'dist', 'shared_dashboard.js'),
        onBuildStart,
        onBuildComplete,
    }),
    buildOrWatch({
        name: 'Toolbar',
        entryPoints: ['src/toolbar/index.tsx'],
        bundle: true,
        format: 'iife',
        outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
        onBuildStart,
        onBuildComplete,
    }),
])
