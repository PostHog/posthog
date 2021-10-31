import { build } from 'esbuild'
import * as path from 'path'
import { __dirname, copyIndexHtml, copyPublicFolder, commonConfig, isWatch } from './esbuild-utils.mjs'
import chokidar from 'chokidar'

copyPublicFolder()
copyIndexHtml()

const time = new Date()
const result = await build({
    ...commonConfig,
    entryPoints: ['src/index.tsx'],
    bundle: true,
    splitting: true,
    format: 'esm',
    outdir: path.resolve(__dirname, 'dist'),
}).catch(() => process.exit(1))
console.log(`🏁 ${isWatch ? 'First full build' : 'Built'} in ${(new Date() - time) / 1000}s`)

async function rebuildApp() {
    const rebuildTime = new Date()
    await result.rebuild()
    console.log(`🔄 Rebuilt in ${(new Date() - rebuildTime) / 1000}s`)
}

let buildPromise = null
let buildAgain = false
async function debouncedRebuild() {
    if (buildPromise) {
        buildAgain = true
        return
    }
    buildAgain = false
    buildPromise = rebuildApp()
    await buildPromise
    buildPromise = null
    if (buildAgain) {
        void debouncedRebuild()
    }
}

if (isWatch) {
    chokidar
        .watch(path.resolve(__dirname, 'src'), {
            ignored: /.*(Type|\.test\.stories)\.[tj]sx$/,
            ignoreInitial: true,
        })
        .on('all', (/* event, path */) => {
            void debouncedRebuild()
        })
}
