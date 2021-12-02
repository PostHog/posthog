#!/usr/bin/env node
import * as path from 'path'
import { __dirname, copyIndexHtml, copyPublicFolder, buildOrWatch, isDev, startServer } from './utils.mjs'
import fse from 'fs-extra'

function writeIndexHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/index.html', 'dist/index.html', 'index', chunks, entrypoints)
    copyIndexHtml('src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints)
}

function writeSharedDashboardHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard', chunks, entrypoints)
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
function onBuildComplete(config, buildResponse) {
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

    // copy "index-TMOJQ3VI.js" -> "index.js"
    for (const entrypoint of entrypoints) {
        const withoutHash = entrypoint.replace(/-([A-Z0-9]+).(js|css)$/, '.$2')
        fse.writeFileSync(
            path.resolve(__dirname, 'dist', withoutHash),
            fse.readFileSync(path.resolve(__dirname, 'dist', entrypoint))
        )
    }

    buildsInProgress--
    if (buildsInProgress === 0) {
        resumeServer()
    }
}

copyPublicFolder()
writeIndexHtml()
writeSharedDashboardHtml()

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
