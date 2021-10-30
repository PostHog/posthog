import { build } from 'esbuild'
import * as path from 'path'
import { __dirname, commonConfig } from './esbuild-utils.mjs'

await build({
    ...commonConfig,
    entryPoints: ['src/toolbar/index.tsx'],
    bundle: true,
    format: 'iife',
    outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
}).catch(() => process.exit(1))
