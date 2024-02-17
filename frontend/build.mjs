#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'

import {
    buildInParallel,
    copyIndexHtml,
    copyPublicFolder,
    createHashlessEntrypoints,
    isDev,
    startDevServer,
} from './utils.mjs'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

startDevServer(__dirname)
copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))
writeIndexHtml()
writeExporterHtml()

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
            publicPath: isDev ? '/static/' : 'https://app.posthog.com/static/',
            alias: {
                'posthog-js': 'posthog-js-lite',
            },
            plugins: [
                {
                    name: 'no-side-effects',
                    setup(build) {
                        // sideEffects in package.json lists files that _have_ side effects,
                        // but we only want to mark lemon-ui as having no side effects,
                        // so we'd have to list every other file and keep that up to date
                        // no thanks!
                        // a glob that negates the path doesn't seem to work
                        // so based off a comment from the esbuild author here
                        // https://github.com/evanw/esbuild/issues/1895#issuecomment-1003404929
                        // we can add a plugin just for the toolbar build to mark lemon-ui as having no side effects
                        // that will allow tree-shaking and reduce the toolbar bundle size
                        // by over 40% at implementation time
                        build.onResolve({ filter: /^(lib|@posthog)\/lemon-ui/ }, async (args) => {
                            if (args.pluginData) {
                                return
                            } // Ignore this if we called ourselves

                            const { path, ...rest } = args
                            rest.pluginData = true // Avoid infinite recursion
                            const result = await build.resolve(path, rest)

                            result.sideEffects = false

                            return result
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
                    throw new Error('Could not get chunk metadata for bundle "PostHog App."')
                }
                if (!isDev && Object.keys(entrypoints).length === 0) {
                    throw new Error('Could not get entrypoint for bundle "PostHog App."')
                }
                writeIndexHtml(chunks, entrypoints)
            }

            if (config.name === 'Exporter') {
                writeExporterHtml(chunks, entrypoints)
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
