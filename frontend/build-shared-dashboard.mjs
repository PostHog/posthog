import { build } from 'esbuild'
import * as path from 'path'
import { __dirname, copyIndexHtml, commonConfig } from './esbuild-utils.mjs'

copyIndexHtml('src/shared_dashboard.html', 'dist/shared_dashboard.html', 'shared_dashboard')

await build({
    ...commonConfig,
    entryPoints: ['src/scenes/dashboard/SharedDashboard.tsx'],
    bundle: true,
    format: 'iife',
    outfile: path.resolve(__dirname, 'dist', 'shared_dashboard.js'),
}).catch(() => process.exit(1))
