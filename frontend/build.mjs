#!/usr/bin/env node
import esbuild from 'esbuild'
import * as path from 'path'
import { dirname } from 'path'
import { fileURLToPath } from 'url'

import {
    commonConfig,
    copyIndexHtml,
    copyPublicFolder,
    createHashlessEntrypoints,
    initializeEsbuild,
    isDev,
    startDevServer,
} from './utils.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

if (isDev) {
    console.log('Starting development server with HMR...')
    startDevServer(__dirname)
    initializeEsbuild()
    copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))
} else {
    console.log('Building for production...')

    const buildConfigs = [
        {
            name: 'PostHog App',
            globalName: 'posthogApp',
            entryPoints: ['src/index.tsx'],
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist'),
            ...commonConfig,
        },
        {
            name: 'Exporter',
            globalName: 'posthogExporter',
            entryPoints: ['src/exporter/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'exporter.js'),
            ...commonConfig,
        },
        {
            name: 'Toolbar',
            globalName: 'posthogToolbar',
            entryPoints: ['src/toolbar/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
            banner: { js: 'var posthogToolbar = (function () { var define = undefined;' },
            footer: { js: 'return posthogToolbar })();' },
            publicPath: isDev ? '/static/' : 'https://us.posthog.com/static/',
            alias: {
                'posthog-js': 'posthog-js-lite',
            },
            writeMetaFile: true,
            extraPlugins: [
                {
                    name: 'no-side-effects',
                    setup(build) {
                        build.onResolve({ filter: /^(lib|@posthog)\/lemon-ui/ }, async (args) => {
                            if (args.pluginData) {
                                return
                            } // Ignore if called recursively

                            const { path, ...rest } = args
                            rest.pluginData = true
                            const result = await build.resolve(path, rest)

                            result.sideEffects = false

                            return result
                        })
                    },
                },
            ],
            ...commonConfig,
        },
    ]

    ;(async () => {
        for (const config of buildConfigs) {
            console.log(`Building: ${config.name}`)
            const result = await esbuild.build(config)

            if (config.name === 'PostHog App') {
                createHashlessEntrypoints(__dirname, Object.keys(result.metafile.outputs))
                copyIndexHtml(__dirname, 'src/index.html', 'dist/index.html', 'index')
            } else if (config.name === 'Exporter') {
                copyIndexHtml(__dirname, 'src/exporter/index.html', 'dist/exporter.html', 'exporter')
            }

            console.log(`${config.name} build complete.`)
        }
    })().catch((error) => {
        console.error('Build failed:', error)
        process.exit(1)
    })
}
