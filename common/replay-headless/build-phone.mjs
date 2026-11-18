import { build } from 'esbuild'
import { mkdirSync, writeFileSync } from 'fs'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
// The mobile app inlines this file into its replay WebView as a string (products/mobile/metro.transformer.js).
// It is generated and gitignored: run this script before a mobile build that uses the WebView replay player.
const output = resolve(__dirname, '../../products/mobile/src/features/replay/web/phonePlayer.generated.js')

const result = await build({
    entryPoints: [resolve(__dirname, 'src/phone-player.ts')],
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    target: 'es2020',
    minify: true,
    sourcemap: false,
    // The phone player does not use the HLS plugin, so hls.js stays out of the bundle.
    external: ['hls.js'],
    define: {
        'process.env.NODE_ENV': '"production"',
        'process.env.LANG': '""',
        'process.env': '{}',
    },
})

mkdirSync(dirname(output), { recursive: true })
writeFileSync(output, result.outputFiles[0].text)
