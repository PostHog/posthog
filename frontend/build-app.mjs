import { build } from 'esbuild'
import * as path from 'path'
import { __dirname, copyIndexHtml, sassPlugin, lessPlugin, copyPublicFolder } from './build-common.mjs'

await build({
    entryPoints: ['src/index.tsx'],
    bundle: true,
    splitting: true,
    format: 'esm',
    resolveExtensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
    outdir: path.resolve(__dirname, 'dist'),
    plugins: [sassPlugin, lessPlugin],
    loader: {
        '.png': 'file',
        '.svg': 'file',
        '.woff': 'file',
        '.woff2': 'file',
        '.mp3': 'file',
    },
}).catch(() => process.exit(1))

copyPublicFolder()
copyIndexHtml()
