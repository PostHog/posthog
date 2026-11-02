#!/usr/bin/env node
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

import {
    buildInParallel,
    commonConfig,
    copyIndexHtml,
    copyPublicFolder,
    copyRRWebWorkerFiles,
    copySnappyWASMFile,
    createHashlessEntrypoints,
    isDev,
    reportTopChunks,
    runExclusiveHeavy,
    startDevServer,
} from '@posthog/esbuilder'
import { minifySeparately } from '@posthog/esbuilder/minify.mjs'

import { AUTHENTICATED_SHELL, ENTRY } from './bin/bootEntries.mjs'
import { LOGGED_OUT_SCENES, moduleKey, sceneModules } from './bin/loggedOutScenes.mjs'
import { writeStableChunks } from './bin/stableChunkNames.mjs'
import { buildCssGroups } from './bin/stableCss.mjs'
import { cssPrelude, CSS_SPECIFIER_PREFIX, planCssGroups } from './bin/stableCssPlan.mjs'
import { removeUnlinkedStylesheets } from './bin/unlinkedStylesheets.mjs'
import { zodJitlessEsbuildPlugin } from './plugins/zodJitless.mjs'
import { finalizeToolbarBuild, getToolbarAppBuildConfig } from './toolbar-config.mjs'
import { WORKER_ENTRIES } from './workers.config.mjs'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Chunks below this size aren't worth a preload tag in the HTML document
const PRELOAD_MIN_CHUNK_BYTES = 50 * 1024

startDevServer(__dirname)
copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))

copyPublicFolder(
    path.resolve(__dirname, 'node_modules', '@posthog', 'hedgehog-mode', 'assets'),
    path.resolve(__dirname, 'dist', 'hedgehog-mode')
)
copyEmojibaseData()
copySnappyWASMFile(__dirname)
copyRRWebWorkerFiles(__dirname)

writeIndexHtml()
writeExporterHtml()
writeRenderQueryHtml()
writeInfrastructureAdminHtml()
await import('./build-products.mjs')

const common = {
    absWorkingDir: __dirname,
    bundle: true,
    writeMetaFile: !isDev,
}

// Not part of `common`: the toolbar spreads `common` over its own config, so an `extraPlugins` key
// there would replace the toolbar's module plugin. The toolbar bundles no zod.
const appBundle = { ...common, extraPlugins: [zodJitlessEsbuildPlugin()] }

await buildInParallel(
    [
        {
            name: 'PostHog App',
            globalName: 'posthogApp',
            entryPoints: ['src/index.tsx', 'src/sharedChunkAnchors.ts'],
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist'),
            heavy: true,
            ...appBundle,
            // minifyAppChunks minifies the identifiers of each chunk on its own, after the build.
            ...(isDev ? {} : { minify: false, minifyWhitespace: true, minifySyntax: true }),
        },
        ...WORKER_ENTRIES.map(({ name, entryPoint, outfileName, define }) => ({
            name,
            entryPoints: [entryPoint],
            format: 'esm',
            outfile: path.resolve(__dirname, 'dist', outfileName),
            ...appBundle,
            ...(define ? { define: { ...commonConfig.define, ...define } } : {}),
        })),
        {
            name: 'Exporter',
            entryPoints: {
                exporter: 'src/exporter/index.tsx',
                exporterSharedChunkAnchors: 'src/sharedChunkAnchors.ts',
            },
            splitting: true,
            format: 'esm',
            outdir: path.resolve(__dirname, 'dist'),
            heavy: true,
            ...appBundle,
        },
        {
            name: 'Render Query',
            globalName: 'posthogRenderQuery',
            entryPoints: ['src/render-query/index.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'render-query.js'),
            ...appBundle,
        },
        {
            name: 'Infrastructure Admin',
            entryPoints: ['../products/tasks/frontend/infrastructure/mountInfrastructureAdmin.tsx'],
            format: 'iife',
            outfile: path.resolve(__dirname, 'dist', 'infrastructure-admin.js'),
            ...appBundle,
        },
        {
            ...getToolbarAppBuildConfig(__dirname),
            ...common,
        },
    ],
    {
        async onBuildComplete(config, buildResponse) {
            if (!buildResponse) {
                return
            }

            const { chunks, entrypoints } = buildResponse

            if (config.name === 'PostHog App') {
                if (Object.keys(chunks).length === 0) {
                    console.error('Could not get chunk metadata for bundle "PostHog App."')
                    throw new Error('Could not get chunk metadata for bundle "PostHog App."')
                }
                if (!isDev && Object.keys(entrypoints).length === 0) {
                    console.error('Could not get entrypoint for bundle "PostHog App."')
                    throw new Error('Could not get entrypoint for bundle "PostHog App."')
                }
                // onBuildComplete runs outside the heavy-build lock, and this work runs esbuild over every chunk.
                const stable = isDev ? null : await runExclusiveHeavy(() => finishAppBuild(buildResponse))
                writeIndexHtml(chunks, entrypoints, stable)
            }

            if (config.name === 'Exporter') {
                if (!isDev) {
                    reportTopChunks(buildResponse.outputs, { label: 'Exporter chunks' })
                    removeUnlinkedStylesheets(__dirname, buildResponse.outputs, 'src/exporter/index.tsx')
                }
                writeExporterHtml(chunks, entrypoints)
            }

            if (config.name === 'Render Query') {
                writeRenderQueryHtml(chunks, entrypoints)
            }

            if (config.name === 'Infrastructure Admin') {
                writeInfrastructureAdminHtml(chunks, entrypoints)
            }

            if (config.name === 'Toolbar') {
                await finalizeToolbarBuild(__dirname, buildResponse)
            }

            createHashlessEntrypoints(__dirname, entrypoints)
        },
    }
)

async function finishAppBuild(buildResponse) {
    const { chunks, entrypoints } = buildResponse
    const unminifiedDir = await minifyAppChunks(buildResponse)
    reportTopChunks(buildResponse.outputs, { label: 'PostHog App chunks' })
    const preloadManifest = writePreloadManifest(buildResponse.outputs)
    // A throw here must fail the build: it reaches buildInParallel's catch, which
    // exits non-zero for non-dev builds. Keep it in this awaited call chain.
    // The stable build also splits the app's CSS: see bin/stableCss.mjs.
    const cssPlan = planCssGroups(buildResponse)
    const cssFiles = await buildCssGroups(__dirname, cssPlan.groups)
    const stable = await writeStableChunks({
        absWorkingDir: __dirname,
        sourceDir: unminifiedDir,
        target: commonConfig.target,
        outputs: buildResponse.outputs,
        chunks,
        entrypoints,
        preloadManifest,
        preludes: new Map(
            [...cssPlan.lazyGroupsByEntry].map(([file, groups]) => [
                file,
                (specifier) => cssPrelude(specifier, groups, cssPlan.rankOfGroup),
            ])
        ),
        extraImports: Object.fromEntries(
            [...cssFiles].map(([group, file]) => [`${CSS_SPECIFIER_PREFIX}${group}`, `static/${file}`])
        ),
        eagerCss: cssPlan.eager.map((group) => cssFiles.get(group)),
        loggedOut: {
            ...loggedOutImportMapScope(),
            cssSpecifiersByOutput: new Map(
                [...cssPlan.lazyGroupsByEntry].map(([file, groups]) => [
                    file,
                    groups.map((group) => `${CSS_SPECIFIER_PREFIX}${group}`),
                ])
            ),
        },
    })
    fs.rmSync(unminifiedDir, { recursive: true, force: true })
    removeUnlinkedStylesheets(__dirname, buildResponse.outputs, 'src/index.tsx')
    return stable
}

/**
 * Minifies every app chunk on its own, in place (see minifySeparately). Keeps the unminified chunks and
 * their maps in the returned directory for the stable copies, and corrects the output sizes that the
 * preload manifest and the eager graph check read.
 *
 * This rewrites each chunk's bytes after esbuild names it, so the default (non-stable) chunk file
 * name is no longer a hash of the bytes it serves.
 */
async function minifyAppChunks(buildResponse) {
    const distDir = path.resolve(__dirname, 'dist')
    const unminifiedDir = path.resolve(__dirname, '.unminified-chunks')
    fs.rmSync(unminifiedDir, { recursive: true, force: true })
    fs.mkdirSync(unminifiedDir)
    const files = Object.keys(buildResponse.outputs)
        .filter((outputPath) => outputPath.endsWith('.js'))
        .map((outputPath) => path.relative(distDir, path.resolve(__dirname, outputPath)))
    const hasMap = (file) => fs.existsSync(path.resolve(distDir, `${file}.map`))
    for (const file of files) {
        fs.mkdirSync(path.dirname(path.resolve(unminifiedDir, file)), { recursive: true })
        fs.renameSync(path.resolve(distDir, file), path.resolve(unminifiedDir, file))
        if (hasMap(file)) {
            fs.copyFileSync(path.resolve(distDir, `${file}.map`), path.resolve(unminifiedDir, `${file}.map`))
        }
    }

    const minified = await minifySeparately(
        files.map((file) => path.resolve(unminifiedDir, file)),
        { inputDir: unminifiedDir, outdir: distDir, target: commonConfig.target }
    )
    for (const file of files) {
        const { code, map } = minified.get(path.resolve(unminifiedDir, file))
        const withMap = hasMap(file)
        const contents = withMap ? `${code}//# sourceMappingURL=${path.basename(file)}.map\n` : code
        fs.writeFileSync(path.resolve(distDir, file), contents)
        if (withMap) {
            fs.writeFileSync(path.resolve(distDir, `${file}.map`), map)
        }
        // esbuild only knows the unminified sizes. Scale each module's share to the minified chunk.
        const output = buildResponse.outputs[`dist/${file}`]
        const bytes = Buffer.byteLength(contents)
        for (const input of Object.values(output.inputs || {})) {
            input.bytesInOutput = Math.round((input.bytesInOutput * bytes) / output.bytes)
        }
        output.bytes = bytes
    }
    fs.writeFileSync(
        path.resolve(__dirname, 'posthog-app-esbuild-meta.json'),
        JSON.stringify({ inputs: buildResponse.inputs, outputs: buildResponse.outputs })
    )
    return unminifiedDir
}

/** Which modules a logged-out page loads, for the logged-out import map. See loggedOutSpecifiers. */
function loggedOutImportMapScope() {
    const scenes = sceneModules(__dirname)
    const missing = LOGGED_OUT_SCENES.filter((scene) => !scenes.has(scene))
    if (missing.length > 0) {
        throw new Error(`stable chunks: no scene loader for the logged-out scenes ${missing.join(', ')}`)
    }
    const loggedOutModules = new Set(LOGGED_OUT_SCENES.map((scene) => scenes.get(scene)))
    const signedInModules = new Set([...scenes.values()].filter((module) => !loggedOutModules.has(module)))
    signedInModules.add(moduleKey(AUTHENTICATED_SHELL))
    return { entry: ENTRY, loggedOutModules, signedInModules }
}

/**
 * Write dist/preload-manifest.json, read by the Django backend (posthog/utils.py) to emit
 * <link rel="preload"/"modulepreload"> tags so the boot chain (CSS, font, App and
 * AuthenticatedShell chunks) is fetched in parallel instead of discovered as a waterfall.
 * Paths are URL suffixes appended to `JS_URL + '/'`.
 */
export function writePreloadManifest(outputs = {}) {
    const distDir = path.resolve(__dirname, 'dist')
    // esbuild metafile paths are relative to absWorkingDir (= __dirname), not the invoking cwd
    const toUrl = (outputPath) => `static/${path.relative(distDir, path.resolve(__dirname, outputPath))}`

    const findEntryJs = (entryPoint) =>
        Object.entries(outputs).find(([out, meta]) => meta.entryPoint === entryPoint && out.endsWith('.js'))

    const collectChunkUrls = (entryPoint) => {
        const found = findEntryJs(entryPoint)
        if (!found) {
            return []
        }
        const [outputPath, meta] = found
        const urls = [toUrl(outputPath)]
        for (const imp of meta.imports || []) {
            if (imp.kind === 'import-statement' && (outputs[imp.path]?.bytes || 0) > PRELOAD_MIN_CHUNK_BYTES) {
                urls.push(toUrl(imp.path))
            }
        }
        return urls
    }

    const cssOutput = Object.keys(outputs).find((out) => /\/index(-[^./-]+)?\.css$/.test(out))
    const fontOutput = Object.keys(outputs).find((out) => /\/Inter(-[^./-]+)?\.woff2$/.test(out))

    const dedupe = (urls) => [...new Set(urls)]
    const manifest = {
        css: cssOutput ? toUrl(cssOutput) : '',
        font: fontOutput ? toUrl(fontOutput) : '',
        // Entry first: its modulepreload starts the fetch at preload-scan time, before the
        // loader script at the end of <head> gets to import() it.
        js: dedupe([...collectChunkUrls('src/index.tsx'), ...collectChunkUrls('src/scenes/App.tsx')]),
        // The backend emits these only for authenticated requests
        authenticatedJs: dedupe(collectChunkUrls('src/scenes/AuthenticatedShell.tsx')),
    }
    // An empty field means an entry point, chunk, or asset name drifted from the lookups above —
    // failing the build beats shipping green with the optimization silently off.
    for (const [key, value] of Object.entries(manifest)) {
        if (value.length === 0) {
            console.error(`preload-manifest.json field "${key}" resolved empty.`)
            throw new Error(`preload-manifest.json field "${key}" resolved empty.`)
        }
    }
    fs.writeFileSync(path.resolve(distDir, 'preload-manifest.json'), JSON.stringify(manifest, null, 2))
    return manifest
}

// EmojiPickerPanel loads frimousse's emoji data from /static/emoji rather than from a CDN. frimousse
// requests only these two files for the `en` locale. The Vite public-assets plugin copies the same files
// in development.
function copyEmojibaseData() {
    const from = path.resolve(__dirname, 'node_modules', 'emojibase-data', 'en')
    const to = path.resolve(__dirname, 'dist', 'emoji', 'en')
    fs.mkdirSync(to, { recursive: true })
    for (const file of ['data.json', 'messages.json']) {
        fs.copyFileSync(path.resolve(from, file), path.resolve(to, file))
    }
}

export function writeIndexHtml(chunks = {}, entrypoints = [], stable = null) {
    copyIndexHtml(__dirname, 'src/index.html', 'dist/index.html', 'index', chunks, entrypoints, stable)
    // layout.html also gets the {% if stable_chunks %} boot branch, but posthog/utils.py only sets
    // stable_chunks for "index.html", so this branch never renders here; the {% else %} default runs.
    copyIndexHtml(__dirname, 'src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints, stable)
}

export function writeExporterHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(__dirname, 'src/exporter/index.html', 'dist/exporter.html', 'exporter', chunks, entrypoints)
}

export function writeInfrastructureAdminHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(
        __dirname,
        '../products/tasks/frontend/infrastructure/infrastructureAdmin.html',
        'dist/infrastructure_admin.html',
        'infrastructure-admin',
        chunks,
        entrypoints
    )
}

export function writeRenderQueryHtml(chunks = {}, entrypoints = []) {
    copyIndexHtml(
        __dirname,
        'src/render-query/index.html',
        'dist/render_query.html',
        'render-query',
        chunks,
        entrypoints
    )
}
