import autoprefixer from 'autoprefixer'
import chokidar from 'chokidar'
import cors from 'cors'
import cssnano from 'cssnano'
import { analyzeMetafile, context } from 'esbuild'
import { lessLoader } from 'esbuild-plugin-less'
import { polyfillNode } from 'esbuild-plugin-polyfill-node'
import { sassPlugin } from 'esbuild-sass-plugin'
import express from 'express'
import fse from 'fs-extra'
import fs from 'node:fs/promises'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import postcss from 'postcss'
import postcssPresetEnv from 'postcss-preset-env'
import ts from 'typescript'

const defaultHost = process.argv.includes('--host') && process.argv.includes('0.0.0.0') ? '0.0.0.0' : 'localhost'
const defaultPort = 8234

export const isDev = process.argv.includes('--dev')

export function copyPublicFolder(srcDir, destDir) {
    fse.copySync(srcDir, destDir, { overwrite: true }, function (err) {
        if (err) {
            console.error(err)
        }
    })
}

export function copySnappyWASMFile(absWorkingDir) {
    try {
        fse.copyFileSync(
            path.resolve(absWorkingDir, 'node_modules/snappy-wasm/es/snappy_bg.wasm'),
            path.resolve(absWorkingDir, 'dist/snappy_bg.wasm')
        )
    } catch (error) {
        console.warn('Could not copy snappy wasm file:', error.message)
    }
}

export function copyRRWebWorkerFiles(absWorkingDir) {
    try {
        const rrwebSourceDir = path.resolve(absWorkingDir, 'node_modules/@posthog/rrweb/dist')
        const distDir = path.resolve(absWorkingDir, 'dist')
        const files = fse.readdirSync(rrwebSourceDir)
        const mapFiles = files.filter((f) => f.startsWith('image-bitmap-data-url-worker-') && f.endsWith('.js.map'))
        mapFiles.forEach((file) => {
            fse.copyFileSync(path.join(rrwebSourceDir, file), path.join(distDir, file))
        })
    } catch (error) {
        console.warn('Could not copy rrweb map files:', error.message)
    }
}

/** Update the file's modified and accessed times to now. */
async function touchFile(file) {
    const now = new Date()
    await fs.utimes(file, now, now)
}

export function copyIndexHtml(
    absWorkingDir = '.',
    from = 'src/index.html',
    to = 'dist/index.html',
    entry = 'index',
    chunks = {},
    entrypoints = []
) {
    // Takes a html file, `from`, and some artifacts from esbuild, and injects
    // some javascript that will load these artifacts dynamically, based on an
    // expected `window.JS_URL` javascript variable.
    //
    // `JS_URL` is expected to be injected into the html as part of Django html
    // template rendering. We do not know what JS_URL should be at runtime, as,
    // for instance, on PostHog Cloud, we want to use the official PostHog
    // Docker image, but serve the js and it's dependencies from e.g. CloudFront
    const buildId = new Date().valueOf()

    const relativeFiles = entrypoints.map((e) => path.relative(path.resolve(absWorkingDir, 'dist'), e))
    const jsFile = relativeFiles.length > 0 ? relativeFiles.find((e) => e.endsWith('.js')) : `${entry}.js?t=${buildId}`
    const cssFile =
        relativeFiles.length > 0 ? relativeFiles.find((e) => e.endsWith('.css')) : `${entry}.css?t=${buildId}`

    const scriptCode = `
        window.ESBUILD_LOAD_SCRIPT = async function (file) {
            try {
                await import((window.JS_URL || '') + '/static/' + file)
            } catch (error) {
                console.error('Error loading chunk: "' + file + '"')
                console.error(error)
            }
        }
        window.ESBUILD_LOAD_SCRIPT(${JSON.stringify(jsFile)})
    `

    // Esbuild "chunks" a scene into possibly hundreds of tiny files. When we load the first few files,
    // they tell us which other files to load. This cascading loading is slow. That's why we cache
    // the list of chunks per scene, and load them all in parallel when a scene is loaded.

    // Don't use chunks in dev mode.
    // Django caches the generated index.html, and we'll end up loading the wrong chunks after one change.
    const chunksToServe = isDev ? {} : chunks
    const chunkCode = `
        window.ESBUILD_LOADED_CHUNKS = new Set(); 
        window.ESBUILD_LOAD_CHUNKS = function(name) { 
            const chunks = ${JSON.stringify(chunksToServe)}[name] || [];
            for (const chunk of chunks) { 
                if (!window.ESBUILD_LOADED_CHUNKS.has(chunk)) { 
                    window.ESBUILD_LOAD_SCRIPT('chunk-'+chunk+'.js'); 
                    window.ESBUILD_LOADED_CHUNKS.add(chunk);
                } 
            } 
        }
        window.ESBUILD_LOAD_CHUNKS('index');
    `

    // Modified CSS loader to handle both files
    const cssLoader = `
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.crossOrigin = "anonymous";
        link.href = (window.JS_URL || '') + "/static/" + ${JSON.stringify(cssFile)};
        document.head.appendChild(link)
    `

    fse.writeFileSync(
        path.resolve(absWorkingDir, to),
        fse.readFileSync(path.resolve(absWorkingDir, from), { encoding: 'utf-8' }).replace(
            '</head>',
            `   <script nonce="{{ request.csp_nonce }}" type="application/javascript">
                    // NOTE: the link for the stylesheet will be added just
                    // after this script block. The react code will need the
                    // body to have been parsed before it is able to interact
                    // with it and add anything to it.
                    //
                    // Fingers crossed the browser waits for the stylesheet to
                    // load such that it's in place when react starts
                    // adding elements to the DOM
                    ${cssFile ? cssLoader : ''}
                    ${scriptCode}
                    ${Object.keys(chunks).length > 0 ? chunkCode : ''}
                </script>
            </head>`
        )
    )
}

/** Makes copies: "index-TMOJQ3VI.js" -> "index.js" */
export function createHashlessEntrypoints(absWorkingDir, entrypoints) {
    for (const entrypoint of entrypoints) {
        const withoutHash = entrypoint.replace(/-([A-Z0-9]+).(js|css)$/, '.$2')
        fse.writeFileSync(
            path.resolve(absWorkingDir, withoutHash),
            fse.readFileSync(path.resolve(absWorkingDir, entrypoint))
        )
    }
}

const tsconfigPath = isDev ? 'tsconfig.dev.json' : 'tsconfig.json'

const { config: tsconfig } = ts.readConfigFile(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', tsconfigPath),
    ts.sys.readFile
)

/** @type {import('esbuild').BuildOptions} */
export const commonConfig = {
    sourcemap: true,
    minify: !isDev,
    target: tsconfig.compilerOptions.target, // We want the same target as tsconfig, should fail if tsconfig not found
    resolveExtensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
    publicPath: '/static',
    assetNames: 'assets/[name]-[hash]',
    chunkNames: '[name]-[hash]',
    // no hashes in dev mode for faster reloads --> we save the old hash in index.html otherwise
    entryNames: isDev ? '[dir]/[name]' : '[dir]/[name]-[hash]',
    plugins: [
        sassPlugin({
            async transform(source, resolveDir, filePath) {
                const plugins = [autoprefixer, postcssPresetEnv({ stage: 0 })]
                if (!isDev) {
                    plugins.push(cssnano({ preset: 'default' }))
                }
                const { css } = await postcss(plugins).process(source, { from: filePath })
                return css
            },
        }),
        lessLoader({ javascriptEnabled: true }),
        polyfillNode({
            polyfills: {
                crypto: true,
            },
        }),
    ],
    tsconfig: tsconfigPath,
    define: {
        global: 'globalThis',
        'process.env.NODE_ENV': isDev ? '"development"' : '"production"',
    },
    loader: {
        '.ttf': 'file',
        '.png': 'file',
        '.svg': 'file',
        '.woff': 'file',
        '.woff2': 'file',
        '.mp3': 'file',
        '.lottie': 'file',
    },
    metafile: true,
}

function getInputFiles(result) {
    return new Set(
        result?.metafile
            ? Object.keys(result.metafile.inputs)
                  .map((key) => (key.includes(':') ? key.split(':')[1] : key))
                  .map((key) => (key.startsWith('/') ? key : path.resolve(process.cwd(), key)))
            : []
    )
}

function getChunks(result) {
    const chunks = {}
    for (const output of Object.values(result.metafile?.outputs || {})) {
        if (!output.entryPoint || output.entryPoint.startsWith('node_modules')) {
            continue
        }
        const importStatements = output.imports.filter(
            (i) => i.kind === 'import-statement' && i.path.startsWith('dist/chunk-')
        )
        const exports = output.exports.filter((e) => e !== 'default' && e !== 'scene')
        if (importStatements.length > 0 && (exports.length > 0 || output.entryPoint === 'src/index.tsx')) {
            chunks[exports[0] || 'index'] = importStatements.map((i) =>
                i.path.replace('dist/chunk-', '').replace('.js', '')
            )
        }
    }
    return chunks
}

export async function buildInParallel(configs, { onBuildStart, onBuildComplete } = {}) {
    try {
        await Promise.all(
            configs.map((config) =>
                buildOrWatch({
                    ...config,
                    onBuildStart,
                    onBuildComplete,
                })
            )
        )
    } catch {
        if (!isDev) {
            process.exit(1)
        }
    }

    if (!isDev) {
        process.exit(0)
    }
}

/** Get the main ".js" and ".css" files for a build */
function getBuiltEntryPoints(config, result) {
    let outfiles = []
    if (config.outdir) {
        // convert "src/index.tsx" --> /a/posthog/frontend/dist/index.js
        outfiles = config.entryPoints.map((file) =>
            path
                .resolve(config.absWorkingDir, file)
                .replace('/src/', '/dist/')
                .replace(/\.[^.]+$/, '.js')
        )
    } else if (config.outfile) {
        outfiles = [path.resolve(config.absWorkingDir, config.outfile)]
    }

    const builtFiles = []
    for (const outfile of outfiles) {
        // convert "/a/something.tsx" --> "/a/something-"
        const fileNoExt = outfile.replace(/\.[^/]+$/, '')
        // find if we built a .js or .css file that matches
        for (const file of Object.keys(result.metafile.outputs)) {
            const absoluteFile = path.resolve(process.cwd(), file)
            if (
                (absoluteFile.startsWith(`${fileNoExt}-`) && (file.endsWith('.js') || file.endsWith('.css'))) ||
                absoluteFile === `${fileNoExt}.js` ||
                absoluteFile === `${fileNoExt}.css`
            ) {
                builtFiles.push(absoluteFile)
            }
        }
    }

    return builtFiles
}

let buildsInProgress = 0

export async function buildOrWatch(config) {
    const { absWorkingDir, name, onBuildStart, onBuildComplete, writeMetaFile, extraPlugins, ..._config } = config

    let buildPromise = null
    let buildAgain = false

    let inputFiles = new Set()

    // The aim is to make sure that when we request a build, then:
    // - we only build one thing at a time
    // - if we request a build when one is running, we'll queue it to start right after this build
    // - if we request a build multiple times when one is running, only one will start right after this build
    // - notify with callbacks when builds start and when they end.
    async function debouncedBuild() {
        if (buildPromise) {
            buildAgain = true
            return
        }
        buildAgain = false
        if (buildsInProgress === 0) {
            server?.pauseServer()
        }
        buildsInProgress++
        onBuildStart?.(config)
        buildPromise = runBuild()
        const buildResponse = await buildPromise
        buildPromise = null
        await onBuildComplete?.(config, buildResponse)
        buildsInProgress--
        if (buildsInProgress === 0) {
            server?.resumeServer()
            reloadLiveServer()
        }

        if (isDev && buildAgain) {
            void debouncedBuild()
        }
    }

    let esbuildContext = null
    let buildCount = 0
    const log = (logOpts) => {
        const icon = logOpts.success === undefined ? '🧱' : logOpts.success ? '🥇' : '🛑'
        let timingSuffix = ''
        if (logOpts.time) {
            timingSuffix = ` in ${(new Date() - logOpts.time) / 1000}s`
        }
        const message =
            logOpts.success === undefined
                ? buildCount === 1
                    ? 'Building'
                    : 'Rebuilding'
                : logOpts.success
                  ? buildCount === 1
                      ? 'Built'
                      : 'Rebuilt'
                  : buildCount === 1
                    ? 'Building failed'
                    : 'Rebuilding failed '

        console.info(`${icon} ${name ? `"${name}": ` : ''}${message}${timingSuffix}`)
    }

    async function runBuild() {
        if (!esbuildContext) {
            const combinedConfig = { ...commonConfig, ..._config }
            combinedConfig.plugins = [...commonConfig.plugins, ...(extraPlugins || [])]
            esbuildContext = await context(combinedConfig)
        }

        buildCount++
        const time = new Date()
        log({ name })
        try {
            const buildResult = await esbuildContext.rebuild()

            if (writeMetaFile) {
                await fs.writeFile(
                    `${config.name.toLowerCase().replace(' ', '-')}-esbuild-meta.json`,
                    JSON.stringify(buildResult.metafile)
                )
            }

            inputFiles = getInputFiles(buildResult)

            log({ success: true, name, time })
            return {
                entrypoints: getBuiltEntryPoints(config, buildResult),
                chunks: getChunks(buildResult),
                ...buildResult.metafile,
            }
        } catch (e) {
            if (isDev) {
                log({ success: false, name, time })
            } else {
                throw e
            }
        }
    }

    if (isDev) {
        chokidar
            .watch(
                [
                    path.resolve(absWorkingDir, 'src'),
                    path.resolve(absWorkingDir, '../ee/frontend'),
                    path.resolve(absWorkingDir, '../common'),
                    path.resolve(absWorkingDir, '../products/*/manifest.tsx'),
                    path.resolve(absWorkingDir, '../products/*/frontend/**/*'),
                ],
                {
                    ignored: /.*(Type|\.test\.stories)\.[tj]sx?$/,
                    ignoreInitial: true,
                }
            )
            .on('all', async (event, filePath) => {
                if (inputFiles.size === 0) {
                    await buildPromise
                }

                // Manifests have been updated, so we need to rebuild urls.
                if (filePath.includes('manifest.tsx')) {
                    await import('../../frontend/build-products.mjs')
                }

                if (inputFiles.has(filePath)) {
                    if (filePath.match(/\.tsx?$/)) {
                        // For changed TS/TSX files, we need to initiate a Tailwind JIT rescan
                        // in case any new utility classes are used. `touch`ing `base.scss` (or the file that imports tailwind.css) achieves this.
                        await touchFile(path.resolve(absWorkingDir, '../common/tailwind/tailwind.css'))
                    }
                    void debouncedBuild()
                }
            })
    }

    await debouncedBuild()
}

export async function printResponse(response, { compact = true, color = true, verbose = false, ...opts } = {}) {
    let text = await analyzeMetafile('metafile' in response ? response.metafile : response, {
        color,
        verbose,
        ...opts,
    })
    if (compact) {
        text = text
            .split('\n')
            .filter((l) => !l.match(/^ {3}[^\n]+$/g) && l.trim())
            .join('\n')
    }
    console.info(text)
}

let clients = new Set()

function reloadLiveServer() {
    clients.forEach((client) => client.write(`data: reload\n\n`))
}

let server

export function startDevServer(absWorkingDir) {
    if (isDev) {
        console.info(`👀 Starting dev server`)
        server = startServer({ absWorkingDir })
        return server
    }
    console.info(`🛳 Starting production build`)
    return null
}

export function startServer(opts = {}) {
    const host = opts.host || defaultHost
    const port = opts.port || defaultPort
    const absWorkingDir = opts.absWorkingDir || '.'

    console.info(`🍱 Starting server at http://${host}:${port}`)

    let resolve = null
    let ifPaused = null

    function pauseServer() {
        if (!ifPaused) {
            ifPaused = new Promise((r) => (resolve = r))
        }
    }

    function resumeServer() {
        resolve?.()
        ifPaused = null
    }

    resumeServer()

    const app = express()
    app.on('error', function (e) {
        if (e.code === 'EADDRINUSE') {
            console.error(`🛑 http://${host}:${port} is already in use. Trying another port.`)
        } else {
            console.error(`🛑 ${e}`)
        }
        process.exit(1)
    })
    app.use(cors())
    app.get('/_reload', (request, response) => {
        response.writeHead(200, {
            'Content-Type': 'text/event-stream',
            Connection: 'keep-alive',
            'Cache-Control': 'no-cache',
        })
        clients.add(response)
        request.on('close', () => clients.delete(response))
    })
    app.get('*', async (req, res) => {
        if (req.url.startsWith('/static/')) {
            if (ifPaused) {
                if (!ifPaused.logged) {
                    console.info('⌛️ Waiting for build to complete...')
                    ifPaused.logged = true
                }
                await ifPaused
            }
            const pathFromUrl = req.url.replace(/^\/static\//, '')
            const filePath = path.resolve(absWorkingDir, 'dist', pathFromUrl)
            // protect against "/../" urls
            if (filePath.startsWith(path.resolve(absWorkingDir, 'dist'))) {
                res.sendFile(filePath.split('?')[0])
                return
            }
        }
        res.sendFile(path.resolve(absWorkingDir, 'dist', 'index.html'))
    })
    app.listen(port)

    return {
        pauseServer,
        resumeServer,
    }
}
