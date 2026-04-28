import { build } from 'esbuild'
import { readFileSync, writeFileSync, mkdirSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

const result = await build({
    entryPoints: [resolve(__dirname, 'src/standalone-player.ts')],
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    target: 'es2020',
    minify: true,
    sourcemap: false,
    metafile: true,
    define: {
        'process.env.NODE_ENV': '"production"',
        'process.env.LANG': '""',
        'process.env': '{}',
    },
})

const js = result.outputFiles[0].text
const html = readFileSync(resolve(__dirname, 'src/index.html'), 'utf-8')
// Use a replacer function to avoid $ replacement patterns in the JS being interpreted
const outputHtml = html.replace('<!-- INLINE_JS -->', () => `<script>${js}</script>`)

mkdirSync(resolve(__dirname, 'dist'), { recursive: true })
writeFileSync(resolve(__dirname, 'dist/player.html'), outputHtml)

// Build protocol module as CJS for nodejs consumers (e.g. recording-rasterizer)
await build({
    entryPoints: [resolve(__dirname, 'src/protocol.ts')],
    bundle: false,
    outfile: resolve(__dirname, 'dist/protocol.js'),
    format: 'cjs',
    platform: 'node',
    target: 'es2020',
})
