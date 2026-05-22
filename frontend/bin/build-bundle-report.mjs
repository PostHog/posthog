#!/usr/bin/env node
import fse from 'fs-extra'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const reportDir = path.join(frontendDir, 'dist-report')

const builds = [
    { name: 'app', metaFile: 'posthog-app-esbuild-meta.json' },
    { name: 'exporter', metaFile: 'exporter-esbuild-meta.json' },
]

function sanitizeSourcePath(p) {
    return p
        .split(path.sep)
        .map((s) => (s === '..' ? '_parent' : s))
        .join(path.sep)
}

fse.removeSync(reportDir)
fse.mkdirSync(reportDir, { recursive: true })

let totalCopied = 0
for (const build of builds) {
    const metaPath = path.join(frontendDir, build.metaFile)
    if (!fse.existsSync(metaPath)) {
        console.warn(`Bundle report: metafile not found for ${build.name} at ${metaPath}, skipping`)
        continue
    }
    const meta = JSON.parse(fse.readFileSync(metaPath, 'utf-8'))

    for (const [outPath, outInfo] of Object.entries(meta.outputs)) {
        if (!outPath.endsWith('.js')) {
            continue
        }
        const src = path.resolve(frontendDir, outPath)
        if (!fse.existsSync(src)) {
            continue
        }

        const baseFile = path.basename(outPath)
        const subPath = outInfo.entryPoint
            ? path.join(sanitizeSourcePath(path.dirname(outInfo.entryPoint)), baseFile)
            : path.join('_chunks', baseFile)

        const dest = path.join(reportDir, build.name, subPath)
        fse.mkdirSync(path.dirname(dest), { recursive: true })
        fse.copyFileSync(src, dest)
        totalCopied++
    }
}

console.info(`Bundle report: wrote ${totalCopied} files to ${reportDir}`)
