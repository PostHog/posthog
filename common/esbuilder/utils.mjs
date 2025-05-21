import fs from 'node:fs/promises'

import autoprefixer from 'autoprefixer'
import * as ps from 'child_process'
import chokidar from 'chokidar'
import cors from 'cors'
import cssnano from 'cssnano'
import { analyzeMetafile, context } from 'esbuild'
import { lessLoader } from 'esbuild-plugin-less'
import { polyfillNode } from 'esbuild-plugin-polyfill-node'
import { sassPlugin } from 'esbuild-sass-plugin'
import express from 'express'
import fse from 'fs-extra'
import * as path from 'path'
import postcss from 'postcss'
import postcssPresetEnv from 'postcss-preset-env'
import ts from 'typescript'
import { cloneNode } from 'ts-clone-node'

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

    const chunkCode = `
        window.ESBUILD_LOADED_CHUNKS = new Set(); 
        window.ESBUILD_LOAD_CHUNKS = function(name) { 
            const chunks = ${JSON.stringify(chunks)}[name] || [];
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
            `   <script type="application/javascript">
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

/** @type {import('esbuild').BuildOptions} */
export const commonConfig = {
    sourcemap: true,
    minify: !isDev,
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
    tsconfig: isDev ? 'tsconfig.dev.json' : 'tsconfig.json',
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
    } catch (e) {
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

        console.log(`${icon} ${name ? `"${name}": ` : ''}${message}${timingSuffix}`)
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
                    gatherProductManifests(absWorkingDir)
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
    console.log(text)
}

let clients = new Set()

function reloadLiveServer() {
    clients.forEach((client) => client.write(`data: reload\n\n`))
}

let server

export function startDevServer(absWorkingDir) {
    if (isDev) {
        console.log(`👀 Starting dev server`)
        server = startServer({ absWorkingDir })
        return server
    }
    console.log(`🛳 Starting production build`)
    return null
}

export function startServer(opts = {}) {
    const host = opts.host || defaultHost
    const port = opts.port || defaultPort
    const absWorkingDir = opts.absWorkingDir || '.'

    console.log(`🍱 Starting server at http://${host}:${port}`)

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
                    console.log('⌛️ Waiting for build to complete...')
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

export function gatherProductUrls(products, __dirname) {
    const sourceFiles = []
    for (const product of products) {
        try {
            if (fse.readFileSync(path.resolve(__dirname, `../products/${product}/manifest.tsx`))) {
                sourceFiles.push(path.resolve(__dirname, `../products/${product}/manifest.tsx`))
            }
        } catch (e) {
            // ignore
        }
    }

    const program = ts.createProgram(sourceFiles, {
        target: 1, // ts.ScriptTarget.ES5
        module: 1, // ts.ModuleKind.CommonJS
        noEmit: true,
        noErrorTruncation: true,
    })

    const urls = []

    for (const sourceFile of program.getSourceFiles()) {
        if (!sourceFiles.includes(sourceFile.fileName)) {
            continue
        }
        ts.forEachChild(sourceFile, function visit(node) {
            if (
                ts.isPropertyAssignment(node) &&
                node.name.text === 'urls' &&
                ts.isObjectLiteralExpression(node.initializer)
            ) {
                for (const property of node.initializer.properties) {
                    urls.push(property)
                }
            } else {
                ts.forEachChild(node, visit)
            }
        })
    }

    const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed })
    const sourceFile = ts.factory.createSourceFile(
        // [ts.factory.createObjectLiteralExpression(urls)],
        [],
        ts.factory.createToken(ts.SyntaxKind.EndOfFileToken),
        ts.NodeFlags.None
    )
    const code = printer.printNode(ts.EmitHint.Unspecified, ts.factory.createObjectLiteralExpression(urls), sourceFile)
    return code
}

export function gatherProductManifests(__dirname) {
    const products = fse
        .readdirSync(path.join(__dirname, '../products'))
        .filter((p) => !['__pycache__', 'README.md'].includes(p))
    const urls = []
    const scenes = []
    const sceneConfigs = []
    const routes = []
    const redirects = []
    const fileSystemTypes = []
    const treeItemsNew = {}
    const treeItemsGames = {}
    const treeItemsProducts = {}
    const fileSystemFilterTypes = []

    const sourceFiles = []
    for (const product of products) {
        try {
            if (fse.readFileSync(path.resolve(__dirname, `../products/${product}/manifest.tsx`))) {
                sourceFiles.push(path.resolve(__dirname, `../products/${product}/manifest.tsx`))
            }
        } catch (e) {
            // ignore
        }
    }

    const program = ts.createProgram(sourceFiles, {
        target: 1, // ts.ScriptTarget.ES5
        module: 1, // ts.ModuleKind.CommonJS
        noEmit: true,
        noErrorTruncation: true,
    })

    /** Helper: Convert a PropertyAssignment from {a: {import:b}} to {a:b} */
    function keepOnlyImport(property, manifestPath) {
        if (ts.isPropertyAssignment(property) && ts.isObjectLiteralExpression(property.initializer)) {
            const imp = property.initializer.properties.find((p) => p.name.text === 'import')
            if (imp) {
                const importFunction = cloneNode(imp.initializer)
                if (
                    ts.isFunctionLike(importFunction) &&
                    ts.isCallExpression(importFunction.body) &&
                    importFunction.body.arguments.length === 1
                ) {
                    const [imported] = importFunction.body.arguments
                    if (ts.isStringLiteralLike(imported)) {
                        const importText = imported.text
                        if (importText.startsWith('./')) {
                            const newPath = path.relative('./src/', path.join(path.dirname(manifestPath), importText))
                            importFunction.body.arguments[0] = ts.factory.createStringLiteral(newPath)
                        }
                    }
                    return ts.factory.createPropertyAssignment(property.name, importFunction)
                }
            }
        }
        return null
    }

    /** Helper: Remove the import key from a PropertyAssignment's ObjectLiteral */
    function withoutImport(property) {
        if (ts.isPropertyAssignment(property) && ts.isObjectLiteralExpression(property.initializer)) {
            const clone = cloneNode(property)
            clone.initializer.properties = clone.initializer.properties.filter((p) => p.name.text !== 'import')
            return clone
        }
        return null
    }

    for (const sourceFile of program.getSourceFiles()) {
        if (!sourceFiles.includes(sourceFile.fileName)) {
            continue
        }
        ts.forEachChild(sourceFile, function visit(node) {
            if (ts.isPropertyAssignment(node) && ts.isObjectLiteralExpression(node.initializer)) {
                if (node.name.text === 'urls') {
                    for (const property of node.initializer.properties) {
                        urls.push(cloneNode(property))
                    }
                } else if (node.name.text === 'routes') {
                    for (const property of node.initializer.properties) {
                        routes.push(cloneNode(property))
                    }
                } else if (node.name.text === 'scenes') {
                    for (const property of node.initializer.properties) {
                        const imp = keepOnlyImport(property, sourceFile.fileName)
                        if (imp) {
                            scenes.push(imp)
                        }
                        const config = withoutImport(property)
                        if (config) {
                            sceneConfigs.push(config)
                        }
                    }
                } else if (node.name.text === 'redirects') {
                    for (const property of node.initializer.properties) {
                        redirects.push(cloneNode(property))
                    }
                } else if (node.name.text === 'fileSystemTypes') {
                    for (const property of node.initializer.properties) {
                        fileSystemTypes.push(cloneNode(property))
                    }
                } else if (node.name.text === 'fileSystemFilterTypes') {
                    for (const property of node.initializer.properties) {
                        fileSystemFilterTypes.push(cloneNode(property))
                    }
                } else {
                    ts.forEachChild(node, visit)
                }
            } else if (
                ts.isPropertyAssignment(node) &&
                ts.isArrayLiteralExpression(node.initializer) &&
                node.name.text === 'treeItemsNew'
            ) {
                for (const element of node.initializer.elements) {
                    if (ts.isObjectLiteralExpression(element)) {
                        const pathNode = element.properties.find((p) => p.name.text === 'path')
                        const path = pathNode ? pathNode.initializer.text : null
                        if (path) {
                            treeItemsNew[path] = cloneNode(element)
                        } else {
                            console.error('Tree item without path:', element)
                        }
                    }
                }
            } else if (
                ts.isPropertyAssignment(node) &&
                ts.isArrayLiteralExpression(node.initializer) &&
                (node.name.text === 'treeItemsProducts' || node.name.text === 'treeItemsGames')
            ) {
                for (const element of node.initializer.elements) {
                    if (ts.isObjectLiteralExpression(element)) {
                        const pathNode = element.properties.find((p) => p.name.text === 'path')
                        const path = pathNode ? pathNode.initializer.text : null
                        if (path) {
                            if (node.name.text === 'treeItemsProducts') {
                                treeItemsProducts[path] = cloneNode(element)
                            } else {
                                treeItemsGames[path] = cloneNode(element)
                            }
                        } else {
                            console.error('Tree item without path:', element)
                        }
                    }
                }
            } else {
                ts.forEachChild(node, visit)
            }
        })
    }

    const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed })
    const sourceFile = ts.factory.createSourceFile(
        [],
        ts.factory.createToken(ts.SyntaxKind.EndOfFileToken),
        ts.NodeFlags.None
    )
    fileSystemTypes.sort((a, b) => a.name.text.localeCompare(b.name.text))
    const manifestUrls = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(urls),
        sourceFile
    )
    const manifestScenes = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(scenes),
        sourceFile
    )
    const manifestSceneConfig = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(sceneConfigs),
        sourceFile
    )
    const manifestRedirects = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(redirects),
        sourceFile
    )
    const manifestRoutes = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(routes),
        sourceFile
    )
    const manifestFileSystemTypes = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(fileSystemTypes),
        sourceFile
    )
    const manifestTreeItemsNew = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createArrayLiteralExpression(
            Object.keys(treeItemsNew)
                .sort()
                .map((key) => treeItemsNew[key])
        ),
        sourceFile
    )
    const manifestTreeItemsProducts = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createArrayLiteralExpression(
            Object.keys(treeItemsProducts)
                .sort()
                .map((key) => treeItemsProducts[key])
        ),
        sourceFile
    )
    const manifestTreeItemsGames = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createArrayLiteralExpression(
            Object.keys(treeItemsGames)
                .sort()
                .map((key) => treeItemsGames[key])
        ),
        sourceFile
    )
    const manifestTreeFilterTypes = printer.printNode(
        ts.EmitHint.Unspecified,
        ts.factory.createObjectLiteralExpression(fileSystemFilterTypes),
        sourceFile
    )

    const autogenComment = '/** This const is auto-generated, as is the whole file */'
    let preservedImports = ''
    const lines = fse.readFileSync(path.join(__dirname, 'src/products.tsx'), 'utf-8').split('\n')
    const importsStarted = lines.findIndex((line) => line.startsWith('import '))
    const importsEnded = lines.findIndex((line) => line.includes(autogenComment))
    preservedImports = lines
        .slice(importsStarted, importsEnded - 1)
        .join('\n')
        .trim()

    if (importsStarted < 0 || importsEnded < 0 || !preservedImports) {
        throw new Error('Could not find existing imports in products.tsx')
    }

    let productsTsx = `
        /* eslint @typescript-eslint/explicit-module-boundary-types: 0 */
        // Generated by @posthog/esbuilder/utils.mjs, based on product folder manifests under products/*/manifest.tsx
        // The imports are preserved between builds, so please update if any are missing or extra.

        ${preservedImports}

        ${autogenComment}
        export const productScenes: Record<string, () => Promise<any>> = ${manifestScenes}\n
        ${autogenComment}
        export const productRoutes: Record<string, [string, string]> = ${manifestRoutes}\n
        ${autogenComment}
        export const productRedirects: Record<string, string | ((params: Params, searchParams: Params, hashParams: Params) => string)> = ${manifestRedirects}\n
        ${autogenComment}
        export const productConfiguration: Record<string, any> = ${manifestSceneConfig}\n
        ${autogenComment}
        export const productUrls = ${manifestUrls}\n
        ${autogenComment}
        export const fileSystemTypes = ${manifestFileSystemTypes}\n
        ${autogenComment}
        export const getTreeItemsNew = (): FileSystemImport[] => ${manifestTreeItemsNew}\n
        ${autogenComment}
        export const getTreeItemsProducts = (): FileSystemImport[] => ${manifestTreeItemsProducts}\n
        ${autogenComment}
        export const getTreeItemsGames = (): FileSystemImport[] => ${manifestTreeItemsGames}\n
        ${autogenComment}
        export const getTreeFilterTypes = (): Record<string, FileSystemFilterType> => (${manifestTreeFilterTypes})\n
    `

    // safe temporary path in /tmp
    fse.mkdirSync(path.join(__dirname, 'tmp'), { recursive: true })
    let tempfile = path.join(__dirname, 'tmp/products.tsx')
    fse.writeFileSync(tempfile, productsTsx)
    ps.execFileSync('prettier', ['--write', tempfile])
    fse.renameSync(tempfile, path.join(__dirname, 'src/products.tsx'))
}
