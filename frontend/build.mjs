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
import fse from 'fs-extra'

let server
function startDevServer() {
    if (isDev) {
        console.log(`👀 Starting dev server`)
        return startServer()
    } else {
        console.log(`🛳 Starting production build`)
        return null
    }
}

export function writeSourceCodeEditorTypes() {
    const readFile = (p) => {
        try {
            return fse.readFileSync(path.resolve(__dirname, p), { encoding: 'utf-8' })
        } catch (e) {
            if (isDev) {
                console.warn(
                    `🙈 Didn't find "${p}" for the app source editor. Build it with: yarn build:packages:types`
                )
            } else {
                throw e
            }
        }
    }
    const types = {
        '@types/react/index.d.ts': readFile('../node_modules/@types/react/index.d.ts'),
        '@types/react/global.d.ts': readFile('../node_modules/@types/react/global.d.ts'),
        '@types/kea/index.d.ts': readFile('../node_modules/kea/lib/index.d.ts'),
        '@posthog/apps-common/index.d.ts': readFile('./packages/apps-common/dist/index.d.ts'),
    }
    fse.writeFileSync(path.resolve(__dirname, './packages/imports.json'), JSON.stringify(types, null, 4) + '\n')
}

export function writeIndexHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/index.html', 'dist/index.html', 'index', chunks, entrypoints)
    copyIndexHtml('src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints)
}

export function writeSharedDashboardHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard', chunks, entrypoints)
}

export function writeExporterHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml('src/exporter.html', 'dist/exporter.html', 'exporter', chunks, entrypoints)
}

startDevServer()
copyPublicFolder()
writeSourceCodeEditorTypes()
writeIndexHtml()
writeSharedDashboardHtml()

let buildsInProgress = 0
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
            name: 'Exporter',
            entryPoints: ['src/exporter/ExportViewer.tsx'],
            bundle: true,
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'exporter.js'),
        },
        {
            name: 'Toolbar',
            entryPoints: ['src/toolbar/index.tsx'],
            bundle: true,
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
        },
        {
            name: 'Apps Common',
            entryPoints: ['packages/apps-common/index.ts'],
            bundle: true,
            format: 'iife',
            outfile: path.resolve(__dirname, 'packages', 'apps-common', 'dist', 'index.js'),
            chunkNames: '[name]',
            entryNames: '[dir]/[name]',
            external: ['react', 'react-dom'],
            minify: true,
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
                if (!isDev && Object.keys(entrypoints).length === 0) {
                    throw new Error('Could not get entrypoint for bundle "PostHog App."')
                }
                writeIndexHtml(chunks, entrypoints)
            }

            if (config.name === 'Shared Dashboard') {
                writeSharedDashboardHtml(chunks, entrypoints)
            }

            if (config.name === 'Exporter') {
                writeExporterHtml(chunks, entrypoints)
            }

            createHashlessEntrypoints(entrypoints)

            buildsInProgress--
            if (buildsInProgress === 0) {
                server?.resumeServer()
            }
        },
    }
)
