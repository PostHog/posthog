#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'
import {
    copyPublicFolder,
    isDev,
    startDevServer,
    createHashlessEntrypoints,
    buildInParallel,
    copyIndexHtml,
} from './utils.mjs'
import fse from 'fs-extra'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

startDevServer(__dirname)
copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))
writeSourceCodeEditorTypes()
writeIndexHtml()
writeSharedDashboardHtml()

const common = {
    absWorkingDir: __dirname,
    bundle: true,
}

await buildInParallel(
    [
        {
            name: 'PostHog App',
            absWorkingDir: __dirname,
            entryPoints: ['src/index.tsx'],
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist'),
            ...common,
        },
        {
            name: 'Shared Dashboard',
            absWorkingDir: __dirname,
            entryPoints: ['src/scenes/dashboard/SharedDashboard.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'shared_dashboard.js'),
            ...common,
        },
        {
            name: 'Exporter',
            absWorkingDir: __dirname,
            entryPoints: ['src/exporter/ExportViewer.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'exporter.js'),
            ...common,
        },
        {
            name: 'Toolbar',
            absWorkingDir: __dirname,
            entryPoints: ['src/toolbar/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
            ...common,
        },
    ],
    {
        async onBuildComplete(config, buildResponse) {
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

            createHashlessEntrypoints(__dirname, entrypoints)
        },
    }
)

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
        '@posthog/apps-common/index.d.ts': readFile('./@posthog/apps-common/dist/index.d.ts'),
    }
    const packagesJsonFile = path.resolve(__dirname, './src/scenes/plugins/source/types/packages.json')
    fse.mkdirpSync(path.dirname(packagesJsonFile))
    fse.writeFileSync(packagesJsonFile, JSON.stringify(types, null, 4) + '\n')
}

export function writeIndexHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(__dirname, 'src/index.html', 'dist/index.html', 'index', chunks, entrypoints)
    copyIndexHtml(__dirname, 'src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints)
}

export function writeSharedDashboardHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(
        __dirname,
        'src/shared_dashboard.html',
        'dist/shared_dashboard.html',
        'shared_dashboard',
        chunks,
        entrypoints
    )
}

export function writeExporterHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(__dirname, 'src/exporter.html', 'dist/exporter.html', 'exporter', chunks, entrypoints)
}
