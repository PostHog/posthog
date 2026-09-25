import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

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
 * hash of its own rewritten bytes, so it changes only when its own code changes.
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

/** Replaces every import of a known chunk by path with an import of its identity specifier. */
export function rewriteChunkSource(source, identityByFile) {
    return source.replace(SOURCE_MAP_COMMENT, '').replace(IMPORT_OF_PATH, (match, keyword, quote, file) => {
        if (!identityByFile.has(file)) {
            return match
        }
        const replacement = `${keyword}${quote}${SPECIFIER_PREFIX}${identityByFile.get(file)}${quote}`
        // Pad to the original byte length so every other offset in the file is unchanged and the
        // esbuild-emitted source map (which points at byte offsets) still lines up. `from"…"`,
        // `import"…"` and `import("…")` all allow whitespace after the closing quote.
        return replacement.padEnd(match.length, ' ')
    })
}

export function alphanumericStem(name) {
    return name.replace(/[^A-Za-z0-9]+(.?)/g, (_, next) => next.toUpperCase())
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
 * Returns, per JS output, its identity, stable file name and rewritten source, plus the import
 * map.
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

    const plan = new Map()
    const imports = {}
    for (const [outputPath] of jsOutputs) {
        const file = fileOf(outputPath)
        const rawSource = readSource(outputPath)
        const source = rewriteChunkSource(rawSource, identityByFile)
        // Every replacement preserves length, except an identity collision with a short entry name
        // (see rewriteChunkSource). When that happens the map's byte offsets no longer line up.
        const mapValid = source.length === rawSource.replace(SOURCE_MAP_COMMENT, '').length
        // A prelude goes on its own first line, so the map only needs to shift down one line.
        const prelude = preludes.get(outputPath) ?? null
        const finalSource = prelude ? `${prelude}\n${source}` : source
        const identity = identityByFile.get(file)
        const stableFile = stableFileName(file, finalSource)
        plan.set(outputPath, { identity, file, stableFile, source: finalSource, mapValid, prelude })
        imports[`${SPECIFIER_PREFIX}${identity}`] = `static/${stableFile}`
    }
    return { plan, imports }
}

/**
 * Writes the stable copies and their source maps next to esbuild's output, and returns the
 * manifest the backend reads. `chunks` is the chunk map (scene name -> esbuild chunk hashes) and
 * `entrypoints` the absolute paths of the entry files, as `buildOrWatch` returns them.
 */
export function writeStableChunks({
    absWorkingDir,
    outputs,
    chunks,
    entrypoints,
    preloadManifest,
    preludes = new Map(),
    extraImports = {},
    eagerCss = [],
}) {
    const distDir = path.resolve(absWorkingDir, 'dist')
    const { plan, imports } = planStableChunks(
        outputs,
        (outputPath) => fs.readFileSync(path.resolve(absWorkingDir, outputPath), 'utf8'),
        'dist/',
        preludes
    )
    Object.assign(imports, extraImports)

    const stableByFile = new Map([...plan.values()].map((entry) => [entry.file, entry.stableFile]))
    for (const { file, stableFile, source, mapValid, prelude } of plan.values()) {
        const mapFile = path.resolve(distDir, `${file}.map`)
        // A rewrite that changed the source's length invalidates the map's byte offsets, so serve
        // the source with no map rather than one that points at the wrong columns.
        const hasMap = fs.existsSync(mapFile) && mapValid
        fs.writeFileSync(
            path.resolve(distDir, stableFile),
            hasMap ? `${source}\n//# sourceMappingURL=${stableFile}.map\n` : source
        )
        if (hasMap && prelude) {
            const map = JSON.parse(fs.readFileSync(mapFile, 'utf8'))
            map.mappings = `;${map.mappings}`
            fs.writeFileSync(path.resolve(distDir, `${stableFile}.map`), JSON.stringify(map))
        } else if (hasMap) {
            fs.copyFileSync(mapFile, path.resolve(distDir, `${stableFile}.map`))
        }
    }

    const toStable = (file) => stableByFile.get(file) ?? file
    const chunkId = (file) => file.replace(/^chunk-/, '').replace(/\.js$/, '')
    const stableChunks = Object.fromEntries(
        Object.entries(chunks).map(([name, list]) => [name, list.map((hash) => chunkId(toStable(`chunk-${hash}.js`)))])
    )
    const stableEntrypoints = entrypoints.map((entrypoint) =>
        entrypoint.endsWith('.js') ? path.resolve(distDir, toStable(path.relative(distDir, entrypoint))) : entrypoint
    )
    const toStableUrl = (url) => `static/${toStable(url.replace(/^static\//, ''))}`
    const manifest = {
        imports,
        eagerCss: eagerCss.map((file) => `static/${file}`),
        preload: {
            js: (preloadManifest?.js || []).map(toStableUrl),
            authenticatedJs: (preloadManifest?.authenticatedJs || []).map(toStableUrl),
        },
    }
    fs.writeFileSync(path.resolve(distDir, 'stable-chunks-manifest.json'), JSON.stringify(manifest))
    return { chunks: stableChunks, entrypoints: stableEntrypoints, eagerCss, manifest }
}
