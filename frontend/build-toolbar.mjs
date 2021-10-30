import { build } from 'esbuild'
import * as path from 'path'
import { __dirname, sassPlugin, lessPlugin } from './build-common.mjs'

await build({
    entryPoints: ['src/toolbar/index.tsx'],
    bundle: true,
    sourcemap: true,
    format: 'iife',
    resolveExtensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
    outfile: path.resolve(__dirname, 'dist', 'toolbar.js'),
    plugins: [sassPlugin, lessPlugin],
    define: {
        global: '{}',
    },
    loader: {
        '.png': 'file',
        '.svg': 'file',
        '.woff': 'file',
        '.woff2': 'file',
        '.mp3': 'file',
    },
}).catch(() => process.exit(1))
