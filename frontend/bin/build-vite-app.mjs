#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
    CHUNK_GRAPH_FILE,
    IMPORT_MAP_FILE,
    MANIFEST_FILE,
    planViteApp,
    shortHash,
    signedInModuleKeys,
    URL_PREFIX,
    VITE_APP_DIR,
} from './viteAppBuild.mjs'

function finishBuild(frontendDir) {
    const outDir = path.join(frontendDir, 'dist', VITE_APP_DIR)
    const graphPath = path.join(outDir, CHUNK_GRAPH_FILE)
    if (!fs.existsSync(graphPath)) {
        throw new Error(`vite app: ${graphPath} is missing. Run \`vite build --config vite.app.config.mts\` first.`)
    }
    const read = (file) => JSON.parse(fs.readFileSync(path.join(outDir, file), 'utf8'))
    // Vite deletes a chunk that held only CSS after the graph was recorded.
    const graph = read(CHUNK_GRAPH_FILE).filter((chunk) => fs.existsSync(path.join(outDir, chunk.fileName)))

    const plan = planViteApp({
        graph,
        importMapUrls: read(IMPORT_MAP_FILE).imports,
        urlBase: `/${URL_PREFIX}`,
        frontendDir,
        signedInModules: signedInModuleKeys(frontendDir),
        readCode: (fileName) => fs.readFileSync(path.join(outDir, fileName), 'utf8'),
        fileSize: (fileName) => fs.statSync(path.join(outDir, fileName)).size,
    })

    for (const [fileName, finalName] of plan.finalNameOf) {
        const from = path.join(outDir, fileName)
        const hasMap = fs.existsSync(`${from}.map`)
        const code = plan.codeOf.get(fileName)
        fs.writeFileSync(
            path.join(outDir, finalName),
            hasMap ? `${code}\n//# sourceMappingURL=${finalName}.map\n` : code
        )
        if (hasMap) {
            fs.renameSync(`${from}.map`, path.join(outDir, `${finalName}.map`))
        }
        fs.rmSync(from)
    }

    const chunkMapSource = `window.VITE_APP_CHUNK_MAP = ${JSON.stringify(plan.chunkMap)};\n`
    const chunkMapFile = `chunk-map-${shortHash(chunkMapSource)}.js`
    fs.writeFileSync(path.join(outDir, chunkMapFile), chunkMapSource)
    fs.writeFileSync(
        path.join(outDir, MANIFEST_FILE),
        JSON.stringify({ ...plan.manifest, assetPrefix: URL_PREFIX, chunkMap: URL_PREFIX + chunkMapFile }, null, 2)
    )

    // Build metadata that the app never requests. The graph stays next to the esbuild metafile for reports.
    fs.renameSync(graphPath, path.join(frontendDir, 'vite-app-graph.json'))
    fs.rmSync(path.join(outDir, IMPORT_MAP_FILE))
    fs.rmSync(path.join(outDir, '.vite'), { recursive: true, force: true })

    const megabytes = (bytes) => `${(bytes / 1e6).toFixed(2)} MB`
    console.info(
        `vite app: ${plan.finalNameOf.size} chunks, ${Object.keys(plan.chunkMap.scenes).length} lazy modules in the chunk map, ` +
            `eager JS ${megabytes(plan.eagerBytes.loggedOut)} logged out and ${megabytes(plan.eagerBytes.authenticated)} signed in`
    )
}

finishBuild(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'))
