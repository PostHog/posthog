import { build } from 'esbuild'
import * as path from 'path'
import {__dirname, copyIndexHtml, copyPublicFolder, commonConfig} from './esbuild-utils.mjs'

await build({
    ...commonConfig,
    entryPoints: ['src/index.tsx'],
    bundle: true,
    splitting: true,
    format: 'esm',
    outdir: path.resolve(__dirname, 'dist'),
}).catch(() => process.exit(1))

copyPublicFolder()
copyIndexHtml()
