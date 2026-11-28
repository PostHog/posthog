import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

import { AUTHENTICATED_SHELL, ENTRY, LOGGED_OUT_BOOT } from './bootEntries.mjs'
import { LOGGED_OUT_SCENES, moduleKey, sceneModules } from './loggedOutScenes.mjs'

/**
 * Prepares the Vite build of the app (vite.app.config.mts) for the backend (posthog/vite_app.py).
 *
 * Vite's chunks import each other through placeholder names, and `importmap.json` maps each
 * placeholder to a file. This step:
 *
 * - Names each chunk by a hash of its final bytes. Vite edits some chunks after it hashes them
 *   (it writes each dynamic import's stylesheet list into the importing chunk), so a Vite file
 *   name can stay the same while the bytes change, and a cache that treats the URL as immutable
 *   then serves the old bytes. Chunks never name each other's files directly, so a rename only
 *   changes the import map.
 * - Writes the chunk map: for each lazy module, every chunk it needs, so the scene loader can
 *   request them all at once and not level by level.
 * - Lists the placeholders a logged-out page can reach, so its import map leaves out the rest.
 * - Writes `vite-app-manifest.json`, which is all the backend reads.
 */

// vite.app.config.mts builds its `build.outDir` and `base` from these two.
export const VITE_APP_DIR = 'vite'
// Manifest paths are relative to JS_URL, the same as in stable-chunks-manifest.json.
export const URL_PREFIX = `static/${VITE_APP_DIR}/`
export const MANIFEST_FILE = 'vite-app-manifest.json'
export const IMPORT_MAP_FILE = 'importmap.json'
export const CHUNK_GRAPH_FILE = 'vite-app-graph.json'

const PRELOAD_MIN_CHUNK_BYTES = 50 * 1024

const SOURCE_MAP_COMMENT = /\n\/\/# sourceMappingURL=[^\n]*\s*$/
const JS_FILE_NAME = /[\w.-]+\.js\b/g

export function shortHash(value) {
    return createHash('sha256').update(value).digest('hex').slice(0, 10).toUpperCase()
}

/** A chunk's code without the trailing source map comment, which names the file and so must not feed its hash. */
export function codeWithoutSourceMapComment(code) {
    return code.replace(SOURCE_MAP_COMMENT, '')
}

/** The `S` marks a name made from the final bytes, like the stable copies of the esbuild build. */
export function finalFileName(chunk, code) {
    const stem = chunk.isEntry ? chunk.name : 'chunk'
    return `${stem}-S${shortHash(code)}.js`
}

/** The module a chunk was made for, as a module key (see loggedOutScenes.mjs), or null for a shared chunk. */
function facadeKey(chunk, frontendDir) {
    if (!chunk.facadeModuleId) {
        return null
    }
    const modulePath = path.relative(frontendDir, chunk.facadeModuleId.split('?')[0])
    return moduleKey(modulePath.split(path.sep).join('/'))
}

export function planViteApp({ graph, importMapUrls, urlBase, frontendDir, signedInModules, readCode, fileSize }) {
    const byFileName = new Map(graph.map((chunk) => [chunk.fileName, chunk]))
    const toFileName = (url) => url.slice(urlBase.length)
    const placeholderOf = new Map(
        Object.entries(importMapUrls)
            .map(([placeholder, file]) => [toFileName(file), toFileName(placeholder)])
            .filter(([fileName]) => byFileName.has(fileName))
    )

    const renamed = graph.filter((chunk) => chunk.isEntry || placeholderOf.has(chunk.fileName))
    const renamedNames = new Set(renamed.map((chunk) => chunk.fileName))
    const codeOf = new Map(
        graph.map((chunk) => [chunk.fileName, codeWithoutSourceMapComment(readCode(chunk.fileName))])
    )
    for (const chunk of graph) {
        for (const [name] of codeOf.get(chunk.fileName).matchAll(JS_FILE_NAME)) {
            if (name !== chunk.fileName && renamedNames.has(name)) {
                // The rename would leave this reference pointing at a file that no longer exists.
                throw new Error(`vite app: ${chunk.fileName} names ${name} directly, not through its placeholder`)
            }
        }
    }
    const finalNameOf = new Map(
        renamed.map((chunk) => [chunk.fileName, finalFileName(chunk, codeOf.get(chunk.fileName))])
    )
    const finalName = (fileName) => finalNameOf.get(fileName) ?? fileName
    const url = (fileName) => URL_PREFIX + fileName

    const closure = (roots, follow = (chunk) => chunk.imports) => {
        const seen = new Set()
        for (const queue = [...roots]; queue.length; ) {
            const chunk = byFileName.get(queue.pop())
            if (chunk && !seen.has(chunk.fileName)) {
                seen.add(chunk.fileName)
                queue.push(...follow(chunk))
            }
        }
        return seen
    }
    const chunkOfModule = (module) => {
        const key = moduleKey(module)
        const chunk = graph.find((candidate) => facadeKey(candidate, frontendDir) === key)
        if (!chunk) {
            throw new Error(`vite app: no chunk for the boot module ${module}`)
        }
        return chunk
    }
    const entry = chunkOfModule(ENTRY)
    const loggedOutBoot = LOGGED_OUT_BOOT.map((module) => chunkOfModule(module).fileName)
    const authenticatedShell = chunkOfModule(AUTHENTICATED_SHELL).fileName

    // Vite orders the stylesheets of a chunk after those of the chunks it imports.
    const stylesheets = (roots) => {
        const css = []
        const seen = new Set()
        const visit = (fileName) => {
            const chunk = byFileName.get(fileName)
            if (!chunk || seen.has(fileName)) {
                return
            }
            seen.add(fileName)
            chunk.imports.forEach(visit)
            for (const file of chunk.css) {
                if (!css.includes(file)) {
                    css.push(file)
                }
            }
        }
        roots.forEach(visit)
        return css
    }
    const eagerCss = stylesheets([entry.fileName])
    const loggedOutCss = stylesheets(loggedOutBoot)
    const authenticatedCss = stylesheets([...loggedOutBoot, authenticatedShell])

    // Each root first, because its preload starts the fetch at preload-scan time, then the large chunks under it.
    const preloadJs = (roots, alreadyLoaded = new Set()) => {
        const large = [...closure(roots)].filter(
            (fileName) => !roots.includes(fileName) && fileSize(fileName) > PRELOAD_MIN_CHUNK_BYTES
        )
        return [...roots, ...large].filter((fileName) => !alreadyLoaded.has(fileName))
    }
    const loggedOutClosure = closure(loggedOutBoot)

    const boot = closure([...loggedOutBoot, authenticatedShell])
    const files = []
    const indexOfFile = new Map()
    const scenes = {}
    for (const chunk of graph) {
        // The same key as getChunks in common/esbuilder/utils.mjs, which the scene loader asks for.
        const key = chunk.exports.find((name) => name !== 'default' && name !== 'scene')
        if (!chunk.isDynamicEntry || !key || chunk.facadeModuleId?.includes('/node_modules/')) {
            continue
        }
        const needed = [...closure([chunk.fileName])].filter((fileName) => !boot.has(fileName))
        if (needed.length > 1) {
            scenes[key] = needed.map((fileName) => {
                if (!indexOfFile.has(fileName)) {
                    indexOfFile.set(fileName, files.push(finalName(fileName)) - 1)
                }
                return indexOfFile.get(fileName)
            })
        }
    }

    const loggedOutReachable = closure([entry.fileName], (chunk) => [
        ...chunk.imports,
        ...chunk.dynamicImports.filter((fileName) => {
            const target = byFileName.get(fileName)
            return !target || !signedInModules.has(facadeKey(target, frontendDir))
        }),
    ])

    return {
        finalNameOf,
        codeOf,
        chunkMap: { files, scenes },
        manifest: {
            entry: url(finalName(entry.fileName)),
            imports: Object.fromEntries(
                [...placeholderOf].map(([fileName, placeholder]) => [url(placeholder), url(finalName(fileName))])
            ),
            loggedOutImports: [...placeholderOf]
                .filter(([fileName]) => loggedOutReachable.has(fileName))
                .map(([, placeholder]) => url(placeholder)),
            eagerCss: eagerCss.map(url),
            preload: {
                js: preloadJs(loggedOutBoot).map(finalName).map(url),
                authenticatedJs: preloadJs([authenticatedShell], loggedOutClosure).map(finalName).map(url),
                css: loggedOutCss.filter((file) => !eagerCss.includes(file)).map(url),
                authenticatedCss: authenticatedCss.filter((file) => !loggedOutCss.includes(file)).map(url),
            },
        },
        eagerBytes: {
            loggedOut: [...loggedOutClosure].reduce((sum, fileName) => sum + fileSize(fileName), 0),
            authenticated: [...boot].reduce((sum, fileName) => sum + fileSize(fileName), 0),
        },
    }
}

export function signedInModuleKeys(frontendDir) {
    const scenes = sceneModules(frontendDir)
    const loggedOut = new Set(LOGGED_OUT_SCENES.map((scene) => scenes.get(scene)))
    const signedIn = new Set([...scenes.values()].filter((module) => !loggedOut.has(module)))
    signedIn.add(moduleKey(AUTHENTICATED_SHELL))
    return signedIn
}

/** Rewrites the output of `vite build --config vite.app.config.mts` in place. See the header of this file. */
export function finishViteAppBuild(frontendDir) {
    const outDir = path.join(frontendDir, 'dist', VITE_APP_DIR)
    const graphPath = path.join(outDir, CHUNK_GRAPH_FILE)
    if (!fs.existsSync(graphPath)) {
        throw new Error(`vite app: ${graphPath} is missing. Run \`vite build --config vite.app.config.mts\` first.`)
    }
    const read = (file) => {
        if (!fs.existsSync(path.join(outDir, file))) {
            throw new Error(
                `vite app: ${path.join(outDir, file)} is missing. Check the \`chunkImportMap\` option in vite.app.config.mts.`
            )
        }
        return JSON.parse(fs.readFileSync(path.join(outDir, file), 'utf8'))
    }
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
