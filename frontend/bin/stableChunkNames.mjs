import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

import { CHUNK_IMPORT_GLOBAL } from '@posthog/esbuilder/cssLoader.mjs'

import { moduleKey } from './loggedOutScenes.mjs'

/**
 * Stable chunk names.
 *
 * esbuild names a chunk by a hash of its bytes, and those bytes contain the hashed file names of
 * every chunk it imports. A change to one chunk therefore renames every chunk that imports it, up
 * to the entry, and returning users download all of them again after a deploy.
 *
 * This step writes a second copy of the app's JS in which chunks import each other through an
 * identity specifier (`@c/<identity>`) instead of a hashed path. An import map, rendered by the
 * backend, resolves each identity to its current file. A chunk's identity comes from the source
 * modules it contains, so it does not change when their code changes. A chunk's file name is a
 * hash of its own rewritten and minified bytes, so it changes only when its own code changes.
 *
 * The app build does not minify identifiers. This step minifies each copy on its own, for the reason
 * in minifySeparately.
 *
 * The copies sit next to esbuild's files in `dist/`, because some chunks resolve workers and wasm
 * files relative to `import.meta.url`. Their names (`<prefix>-S<10 hex>.js`) cannot collide with
 * esbuild's 8-character base32 hashes.
 */

export const SPECIFIER_PREFIX = '@c/'
export const STABLE_NAME_MARKER = 'S'

const SOURCE_MAP_COMMENT = /\n\/\/# sourceMappingURL=[^\n]*\s*$/

export function shortHash(value) {
    return createHash('sha256').update(value).digest('hex').slice(0, 10).toUpperCase()
}

/**
 * Identity of an output chunk. Entry chunks use their entry point. Shared chunks use the set of
 * source modules esbuild placed in them, which is stable while the module graph is stable.
 */
export function chunkIdentity(output) {
    if (output.entryPoint) {
        return `e${shortHash(output.entryPoint)}`
    }
    return `c${shortHash(
        Object.keys(output.inputs || {})
            .sort()
            .join('\n')
    )}`
}

// A chunk path in import position: `from"…"`, `import"…"` and `import("…")`. Only these resolve through
// the import map. The same path passed to new URL(), fetch() or a Worker must stay a real URL.
const IMPORT_OF_PATH = /(\bfrom\s*|\bimport\s*\(?\s*)(["'])\/static\/([^"'\s]+?\.js)\2/g

const isDynamicImport = (keyword) => keyword.trimEnd().endsWith('(')

/**
 * Replaces every import of a known chunk by path with an import of its identity specifier. A
 * dynamic import of a chunk in `cssChunkFiles` goes through `window.ESBUILD_IMPORT`, which waits
 * for the stylesheets that chunk registers.
 */
export function rewriteChunkSource(source, identityByFile, cssChunkFiles = new Set()) {
    return source.replace(SOURCE_MAP_COMMENT, '').replace(IMPORT_OF_PATH, (match, keyword, quote, file) => {
        if (!identityByFile.has(file)) {
            return match
        }
        const importer = cssChunkFiles.has(file) && isDynamicImport(keyword) ? `${CHUNK_IMPORT_GLOBAL}(` : keyword
        const replacement = `${importer}${quote}${SPECIFIER_PREFIX}${identityByFile.get(file)}${quote}`
        // Pad to the original byte length so every other offset in the file is unchanged and the
        // esbuild-emitted source map (which points at byte offsets) still lines up. `from"…"`,
        // `import"…"` and `import("…")` all allow whitespace after the closing quote.
        return replacement.padEnd(match.length, ' ')
    })
}

export function alphanumericStem(name) {
    return name.replace(/[^A-Za-z0-9]+(.?)/g, (_, next) => next.toUpperCase())
}

/**
 * Shifts a source map's mappings down by the one line a prelude occupies. A `;` with no VLQ
 * segments before it marks that first generated line as empty, so everything the original map
 * described moves down to line two.
 */
export function shiftMappingsForPrelude(mappings) {
    return `;${mappings}`
}

export function stableFileName(originalFile, rewrittenSource) {
    const prefix = originalFile.replace(/-[^-./]+\.js$/, '')
    // Only holds because chunkNames/entryNames in common/esbuilder/utils.mjs are `[name]-[hash]` for non-dev builds.
    // Fail loudly rather than silently producing a garbled name like `index.js-S....js`.
    if (prefix === originalFile) {
        throw new Error(`stable chunks: ${originalFile} does not end in the expected -<hash>.js suffix`)
    }
    return `${alphanumericStem(prefix)}-${STABLE_NAME_MARKER}${shortHash(rewrittenSource)}.js`
}

/**
 * Plans the stable copy of a build. `outputs` is the esbuild metafile's `outputs`, and
 * `readSource(outputPath)` returns an output file's contents. Pure apart from `readSource`.
 *
 * `preludes` maps an output path to a function of its specifier that returns the chunk's first line.
 *
 * Returns, per JS output, its identity and rewritten source.
 */
export function planStableChunks(outputs, readSource, distPrefix = 'dist/', preludes = new Map()) {
    const jsOutputs = Object.entries(outputs).filter(([outputPath]) => outputPath.endsWith('.js'))
    const fileOf = (outputPath) => outputPath.slice(distPrefix.length)

    const identityByFile = new Map()
    const seen = new Map()
    for (const [outputPath, output] of jsOutputs) {
        let identity = chunkIdentity(output)
        if (seen.has(identity)) {
            // Two chunks with the same inputs cannot come out of one build, but an empty chunk
            // could. Fall back to the esbuild name: unique within the build, only less stable.
            console.warn(
                `stable chunks: identity collision for ${outputPath}, falling back to an esbuild-hash-derived name`
            )
            identity = `${identity}${shortHash(outputPath)}`
        }
        seen.set(identity, outputPath)
        identityByFile.set(fileOf(outputPath), identity)
    }

    const cssChunkFiles = new Set([...preludes.keys()].map(fileOf))
    const plan = new Map()
    for (const [outputPath] of jsOutputs) {
        const file = fileOf(outputPath)
        const rawSource = readSource(outputPath)
        const source = rewriteChunkSource(rawSource, identityByFile, cssChunkFiles)
        // Every replacement preserves length, unless it outgrows a very short chunk name (an identity
        // collision, or ESBUILD_IMPORT). When that happens the map's byte offsets no longer line up.
        const mapValid = source.length === rawSource.replace(SOURCE_MAP_COMMENT, '').length
        // A prelude goes on its own first line, so the map only needs to shift down one line.
        const identity = identityByFile.get(file)
        const prelude = preludes.get(outputPath)?.(`${SPECIFIER_PREFIX}${identity}`) ?? null
        const finalSource = prelude ? `${prelude}\n${source}` : source
        plan.set(outputPath, { identity, file, source: finalSource, mapValid, prelude })
    }
    return { plan }
}

/**
 * The import map specifiers a logged-out page can reach. The walk starts at the chunk of `entry`
 * and follows every import, except a dynamic import of a module in `signedInModules`. Modules are
 * module keys (see loggedOutScenes.mjs). Each module in `loggedOutModules` must be reached.
 *
 * `outputs` is the esbuild metafile's `outputs`, and `plan` is the plan from planStableChunks.
 */
export function loggedOutSpecifiers(
    outputs,
    plan,
    { entry, loggedOutModules, signedInModules, cssSpecifiersByOutput }
) {
    const moduleOf = (output) => (output.entryPoint ? moduleKey(output.entryPoint) : null)
    const start = Object.keys(outputs).find(
        (outputPath) => outputPath.endsWith('.js') && moduleOf(outputs[outputPath]) === moduleKey(entry)
    )
    if (!start) {
        throw new Error(`stable chunks: no output chunk for the entry ${entry}`)
    }
    const reached = new Set([start])
    const queue = [start]
    while (queue.length > 0) {
        for (const { path: target, kind } of outputs[queue.pop()].imports || []) {
            const output = outputs[target]
            if (!output || !target.endsWith('.js') || reached.has(target)) {
                continue
            }
            if (kind === 'dynamic-import' && signedInModules.has(moduleOf(output))) {
                continue
            }
            reached.add(target)
            queue.push(target)
        }
    }

    // A logged-out scene that the walk misses would load with no import map entries for its chunks.
    const reachedModules = new Set([...reached].map((outputPath) => moduleOf(outputs[outputPath])))
    const unreached = [...loggedOutModules].filter((module) => !reachedModules.has(module))
    if (unreached.length > 0) {
        throw new Error(`stable chunks: logged-out scenes not reachable from ${entry}: ${unreached.join(', ')}`)
    }

    const specifiers = new Set()
    for (const outputPath of reached) {
        specifiers.add(`${SPECIFIER_PREFIX}${plan.get(outputPath).identity}`)
        for (const specifier of cssSpecifiersByOutput.get(outputPath) ?? []) {
            specifiers.add(specifier)
        }
    }
    return [...specifiers].sort()
}

/**
 * Writes the stable copies and their source maps next to esbuild's output, and returns the
 * manifest the backend reads. `chunks` is the chunk map (scene name -> esbuild chunk hashes) and
 * `entrypoints` the absolute paths of the entry files, as `buildOrWatch` returns them. `loggedOut`
 * holds the options for loggedOutSpecifiers. Without it, every page gets the full import map.
 * `sourceDir` holds the build's unminified chunks and their maps, when they are no longer in `dist/`.
 */
export async function writeStableChunks({
    absWorkingDir,
    sourceDir = path.resolve(absWorkingDir, 'dist'),
    target,
    outputs,
    chunks,
    entrypoints,
    preloadManifest,
    preludes = new Map(),
    extraImports = {},
    eagerCss = [],
    loggedOut = null,
}) {
    const distDir = path.resolve(absWorkingDir, 'dist')
    const sourceOf = (file) => path.resolve(sourceDir, file)
    const { plan } = planStableChunks(
        outputs,
        (outputPath) => fs.readFileSync(sourceOf(outputPath.slice('dist/'.length)), 'utf8'),
        'dist/',
        preludes
    )

    // A sibling of dist/, so the relative source paths in the maps resolve the same way.
    const rewrittenDir = path.resolve(absWorkingDir, '.stable-chunks-rewritten')
    fs.rmSync(rewrittenDir, { recursive: true, force: true })
    fs.mkdirSync(rewrittenDir)
    try {
        const hasMapByFile = new Map()
        for (const { file, source, mapValid, prelude } of plan.values()) {
            const mapFile = sourceOf(`${file}.map`)
            // A rewrite that changed the source's length invalidates the map's byte offsets, so serve
            // the source with no map rather than one that points at the wrong columns.
            const hasMap = fs.existsSync(mapFile) && mapValid
            hasMapByFile.set(file, hasMap)
            fs.writeFileSync(
                path.resolve(rewrittenDir, file),
                hasMap ? `${source}\n//# sourceMappingURL=${file}.map\n` : source
            )
            if (hasMap) {
                const map = JSON.parse(fs.readFileSync(mapFile, 'utf8'))
                if (prelude) {
                    map.mappings = shiftMappingsForPrelude(map.mappings)
                }
                fs.writeFileSync(path.resolve(rewrittenDir, `${file}.map`), JSON.stringify(map))
            }
        }

        // Imported here, not at the top: esbuild refuses to load under jsdom, where the planning tests run.
        const { minifySeparately } = await import('@posthog/esbuilder/minify.mjs')
        const minified = await minifySeparately(
            [...plan.values()].map(({ file }) => path.resolve(rewrittenDir, file)),
            { inputDir: rewrittenDir, outdir: distDir, target }
        )
        const imports = {}
        const stableByFile = new Map()
        for (const { identity, file } of plan.values()) {
            const { code, map } = minified.get(path.resolve(rewrittenDir, file))
            const stableFile = stableFileName(file, code)
            const hasMap = hasMapByFile.get(file)
            fs.writeFileSync(
                path.resolve(distDir, stableFile),
                hasMap ? `${code}//# sourceMappingURL=${stableFile}.map\n` : code
            )
            if (hasMap) {
                fs.writeFileSync(path.resolve(distDir, `${stableFile}.map`), map)
            }
            imports[`${SPECIFIER_PREFIX}${identity}`] = `static/${stableFile}`
            stableByFile.set(file, stableFile)
        }
        Object.assign(imports, extraImports)

        const toStable = (file) => stableByFile.get(file) ?? file
        const chunkId = (file) => file.replace(/^chunk-/, '').replace(/\.js$/, '')
        const stableChunks = Object.fromEntries(
            Object.entries(chunks).map(([name, list]) => [
                name,
                list.map((hash) => chunkId(toStable(`chunk-${hash}.js`))),
            ])
        )
        const stableEntrypoints = entrypoints.map((entrypoint) =>
            entrypoint.endsWith('.js')
                ? path.resolve(distDir, toStable(path.relative(distDir, entrypoint)))
                : entrypoint
        )
        const toStableUrl = (url) => `static/${toStable(url.replace(/^static\//, ''))}`
        const manifest = {
            imports,
            eagerCss: eagerCss.map((file) => `static/${file}`),
            // The backend renders only these import map entries for a logged-out page.
            loggedOutImports: loggedOut ? loggedOutSpecifiers(outputs, plan, loggedOut) : null,
            preload: {
                js: (preloadManifest?.js || []).map(toStableUrl),
                authenticatedJs: (preloadManifest?.authenticatedJs || []).map(toStableUrl),
            },
        }
        fs.writeFileSync(path.resolve(distDir, 'stable-chunks-manifest.json'), JSON.stringify(manifest))
        return { chunks: stableChunks, entrypoints: stableEntrypoints, eagerCss, manifest }
    } finally {
        fs.rmSync(rewrittenDir, { recursive: true, force: true })
    }
}
