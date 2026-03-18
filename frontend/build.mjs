#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'

import {
    buildInParallel,
    copyIndexHtml,
    copyPublicFolder,
    copyRRWebWorkerFiles,
    copySnappyWASMFile,
    createHashlessEntrypoints,
    isDev,
    startDevServer,
} from '@posthog/esbuilder'

import { getToolbarBuildConfig } from './toolbar-config.mjs'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

startDevServer(__dirname)
copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))

copyPublicFolder(
    path.resolve(__dirname, 'node_modules', '@posthog', 'hedgehog-mode', 'assets'),
    path.resolve(__dirname, 'dist', 'hedgehog-mode')
)
copySnappyWASMFile(__dirname)
copyRRWebWorkerFiles(__dirname)

writeIndexHtml()
writeExporterHtml()
writeRenderQueryHtml()
await import('./build-products.mjs')

const common = {
    absWorkingDir: __dirname,
    bundle: true,
}

await buildInParallel(
    [
        {
            name: 'PostHog App',
            globalName: 'posthogApp',
            entryPoints: ['src/index.tsx'],
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist'),
            ...common,
        },
        {
            name: 'Decompression Worker',
            entryPoints: ['src/scenes/session-recordings/player/snapshot-processing/decompressionWorker.ts'],
            format: 'esm',
            outfile: path.resolve(__dirname, 'dist', 'decompressionWorker.js'),
            ...common,
        },
        {
            name: 'Exporter',
            globalName: 'posthogExporter',
            entryPoints: ['src/exporter/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'exporter.js'),
            ...common,
        },
        {
            name: 'Render Query',
            globalName: 'posthogRenderQuery',
            entryPoints: ['src/render-query/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'render-query.js'),
            ...common,
        },
        {
            ...getToolbarBuildConfig(__dirname),
            ...common,
        },
    ],
    {
        async onBuildComplete(config, buildResponse) {
            if (!buildResponse) {
                return
            }

            const { chunks, entrypoints } = buildResponse

            if (config.name === 'PostHog App') {
                if (Object.keys(chunks).length === 0) {
                    console.error('Could not get chunk metadata for bundle "PostHog App."')
                    throw new Error('Could not get chunk metadata for bundle "PostHog App."')
                }
                if (!isDev && Object.keys(entrypoints).length === 0) {
                    console.error('Could not get entrypoint for bundle "PostHog App."')
                    throw new Error('Could not get entrypoint for bundle "PostHog App."')
                }
                writeIndexHtml(chunks, entrypoints)
            }

            if (config.name === 'Exporter') {
                writeExporterHtml(chunks, entrypoints)
            }

            if (config.name === 'Render Query') {
                writeRenderQueryHtml(chunks, entrypoints)
            }

            createHashlessEntrypoints(__dirname, entrypoints)
        },
    }
)

export function writeIndexHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(__dirname, 'src/index.html', 'dist/index.html', 'index', chunks, entrypoints)
    copyIndexHtml(__dirname, 'src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints)
}

export function writeExporterHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(__dirname, 'src/exporter/index.html', 'dist/exporter.html', 'exporter', chunks, entrypoints)
}

export function writeRenderQueryHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(
        __dirname,
        'src/render-query/index.html',
        'dist/render_query.html',
        'render-query',
        chunks,
        entrypoints
    )
}
