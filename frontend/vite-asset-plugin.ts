import * as fs from 'fs'
import fse from 'fs-extra'
import * as path from 'path'
import { Plugin } from 'vite'

/**
 * Vite plugin to replicate ESBuild's asset copying functionality
 * This includes:
 * - Copying public folder to dist
 * - Copying snappy WASM file
 * - Copying RRWeb worker files
 */
export function assetCopyPlugin(): Plugin {
    return {
        name: 'posthog-asset-copy',
        generateBundle() {
            const projectRoot = process.cwd()
            const distDir = path.resolve(projectRoot, 'dist')

            // Ensure dist directory exists
            fse.ensureDirSync(distDir)

            // 1. Copy public folder (similar to copyPublicFolder in ESBuild)
            const publicDir = path.resolve(projectRoot, 'public')
            if (fs.existsSync(publicDir)) {
                fse.copySync(publicDir, distDir, { overwrite: true })
            }

            // 2. Copy snappy WASM file (similar to copySnappyWASMFile in ESBuild)
            try {
                const snappyWasmSource = path.resolve(projectRoot, 'node_modules/snappy-wasm/es/snappy_bg.wasm')
                const snappyWasmDest = path.resolve(distDir, 'snappy_bg.wasm')

                if (fs.existsSync(snappyWasmSource)) {
                    fse.copyFileSync(snappyWasmSource, snappyWasmDest)
                } else {
                    console.warn('⚠️  Snappy WASM file not found at expected location')
                }
            } catch (error) {
                console.warn('⚠️  Could not copy snappy WASM file:', error.message)
            }

            // 3. Copy RRWeb worker files (similar to copyRRWebWorkerFiles in ESBuild)
            try {
                const rrwebSourceDir = path.resolve(projectRoot, 'node_modules/@posthog/rrweb/dist')

                if (fs.existsSync(rrwebSourceDir)) {
                    const files = fs.readdirSync(rrwebSourceDir)
                    const mapFiles = files.filter(
                        (f) => f.startsWith('image-bitmap-data-url-worker-') && f.endsWith('.js.map')
                    )

                    if (mapFiles.length > 0) {
                        mapFiles.forEach((file) => {
                            fse.copyFileSync(path.join(rrwebSourceDir, file), path.join(distDir, file))
                        })
                    }
                } else {
                    console.warn('⚠️  RRWeb dist directory not found')
                }
            } catch (error) {
                console.warn('⚠️  Could not copy RRWeb worker files:', error.message)
            }
        },
    }
}
