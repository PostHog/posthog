import * as path from 'path'
import { __dirname, copyIndexHtml, copyPublicFolder, buildOrWatch, isWatch } from './esbuild-utils.mjs'

copyPublicFolder()
copyIndexHtml()
copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard')

if (isWatch) {
    console.log(`👀 Starting watch mode`)
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
    }),
    buildOrWatch({
        name: 'Shared Dashboard',
        entryPoints: ['src/scenes/dashboard/SharedDashboard.tsx'],
        bundle: true,
        format: 'iife',
        outfile: path.resolve(__dirname, 'dist', 'shared_dashboard.js'),
    }),
    buildOrWatch({
        name: 'Toolbar',
        entryPoints: ['src/toolbar/index.tsx'],
        bundle: true,
        format: 'iife',
        outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
    }),
])
