import { build } from 'esbuild'
import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
// The mobile app inlines this file into its replay WebView as a string (products/mobile/metro.transformer.js).
// The mobile workspace ships the generated asset so its standalone checkout can build it into the app.
const output = resolve(__dirname, '../../products/mobile/src/features/replay/web/phonePlayer.generated.replay')

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

const bundle = result.outputFiles[0].text
if (process.argv.includes('--check')) {
    if (readFileSync(output, 'utf8') !== bundle) {
        throw new Error('Run pnpm --filter @posthog/replay-headless build:phone to update the mobile replay bundle.')
    }
} else {
    mkdirSync(dirname(output), { recursive: true })
    writeFileSync(output, bundle)
}
