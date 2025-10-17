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

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

startDevServer(__dirname)
copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))
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
            name: 'Toolbar',
            globalName: 'posthogToolbar',
            entryPoints: ['src/toolbar/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
            // make sure we don't link to a global window.define
            banner: { js: 'var posthogToolbar = (function () { var define = undefined;' },
            footer: { js: 'return posthogToolbar })();' },
            // This isn't great, but we load some static assets at runtime for the toolbar, and we can't sub in
            // a variable at runtime it seems...
            publicPath: isDev ? '/static/' : 'https://us.posthog.com/static/',
            writeMetaFile: true,
            extraPlugins: [
                {
                    /**
                     * The toolbar includes many parts of the main posthog app,
                     * but we don't want to include everything in the toolbar bundle.
                     * Partly because it would be too big, and partly because some things
                     * in the main app cause problems for people using CSPs on their sites.
                     *
                     * It wasn't possible to tree-shake the dependencies out of the bundle,
                     * and we don't want to change the app code significantly just for the toolbar
                     *
                     * So instead we replace some imports in the toolbar with a fake empty module
                     *
                     * This is ever so slightly hacky, but it gets customers up and running
                     *
                     * */
                    name: 'denylist-imports',
                    setup(build) {
                        // Explicit denylist of paths we don't want in the toolbar bundle
                        const deniedPaths = [
                            '~/lib/hooks/useUploadFiles',
                            '~/queries/nodes/InsightViz/InsightViz',
                            'lib/hog',
                            'scenes/activity/explore/EventDetails',
                            'scenes/web-analytics/WebAnalyticsDashboard',
                            'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager.ts',
                        ]

                        // Patterns to match for denying imports
                        const deniedPatterns = [
                            /monaco/,
                            /scenes\/insights\/filters\/ActionFilter/,
                            /lib\/components\/CodeSnippet/,
                            /scenes\/session-recordings\/player/,
                            /queries\/schema-guard/,
                            /queries\/schema.json/,
                            /queries\/QueryEditor\/QueryEditor/,
                            /scenes\/billing/,
                            /scenes\/data-warehouse/,
                            /LineGraph/,
                        ]

                        build.onResolve({ filter: /.*/ }, (args) => {
                            const shouldDeny =
                                deniedPaths.includes(args.path) ||
                                deniedPatterns.some((pattern) => pattern.test(args.path))

                            if (shouldDeny) {
                                return {
                                    path: args.path,
                                    namespace: 'empty-module',
                                    sideEffects: false,
                                }
                            }
                        })

                        build.onLoad({ filter: /.*/, namespace: 'empty-module' }, (args) => {
                            return {
                                contents: `
                                module.exports = new Proxy({}, {
                                    get: function() {
                                        const shouldLog = window?.posthog?.config?.debug
                                        if (shouldLog) {
                                            console.warn('[TOOLBAR] Attempted to use denied module:', ${JSON.stringify(
                                                args.path
                                            )});
                                        }
                                        return function() {
                                            return {}
                                        }
                                    }
                                });
                            `,
                                loader: 'js',
                            }
                        })
                    },
                },
            ],
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
