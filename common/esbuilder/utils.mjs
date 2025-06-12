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
import { cloneNode } from 'ts-clone-node'
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

export function gatherProductManifests(__dirname) {
    // ──────────────────────────
    // 1. Scan for manifest files
    // ──────────────────────────
    const productsDir = path.join(__dirname, '../products')
    const products = fse.readdirSync(productsDir).filter((p) => !['__pycache__', 'README.md'].includes(p))
    const sourceFiles = products
        .map((p) => path.resolve(productsDir, `${p}/manifest.tsx`))
        .filter((p) => fse.existsSync(p))

    const program = ts.createProgram(sourceFiles, {
        target: 1, // ES5
        module: 1, // CommonJS
        noEmit: true,
        noErrorTruncation: true,
    })

    // ─────────────────────────────
    // 2. Gather manifest properties
    // ─────────────────────────────
    const urls = []
    const scenes = []
    const sceneConfigs = []
    const routes = []
    const redirects = []
    const fileSystemTypes = []
    const treeItemsNew = {}
    const treeItemsGames = {}
    const treeItemsMetadata = {}
    const treeItemsProducts = {}

    const visitManifests = (sourceFile) => {
        ts.forEachChild(sourceFile, function walk(node) {
            if (ts.isPropertyAssignment(node) && ts.isObjectLiteralExpression(node.initializer)) {
                const { text: name } = node.name
                const list = {
                    urls,
                    routes,
                    redirects,
                    fileSystemTypes,
                }[name]
                if (list) {
                    node.initializer.properties.forEach((p) => list.push(cloneNode(p)))
                } else if (name === 'scenes') {
                    node.initializer.properties.forEach((prop) => {
                        const imp = keepOnlyImport(prop, sourceFile.fileName)
                        if (imp) {
                            scenes.push(imp)
                        }
                        const cfg = withoutImport(prop)
                        if (cfg) {
                            sceneConfigs.push(cfg)
                        }
                    })
                } else {
                    ts.forEachChild(node, walk)
                }
            } else if (
                ts.isPropertyAssignment(node) &&
                ts.isArrayLiteralExpression(node.initializer) &&
                ['treeItemsNew', 'treeItemsProducts', 'treeItemsMetadata', 'treeItemsGames'].includes(node.name.text)
            ) {
                const dict =
                    node.name.text === 'treeItemsNew'
                        ? treeItemsNew
                        : node.name.text === 'treeItemsProducts'
                        ? treeItemsProducts
                        : node.name.text === 'treeItemsMetadata'
                        ? treeItemsMetadata
                        : treeItemsGames
                node.initializer.elements.forEach((el) => {
                    if (!ts.isObjectLiteralExpression(el)) {
                        return
                    }
                    const pathProp = el.properties.find((p) => p.name?.text === 'path')
                    const thePath = pathProp?.initializer?.text
                    if (thePath) {
                        dict[thePath] = cloneNode(el)
                    }
                })
            } else {
                ts.forEachChild(node, walk)
            }
        })
    }

    for (const sf of program.getSourceFiles()) {
        if (sourceFiles.includes(sf.fileName)) {
            visitManifests(sf)
        }
    }

    // ──────────────────────────────
    // 3. Convert AST → printable code
    // ──────────────────────────────
    const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed })
    const makeObjExpr = (nodes) =>
        printer.printNode(
            ts.EmitHint.Unspecified,
            ts.factory.createObjectLiteralExpression(nodes),
            ts.createSourceFile('', '', ts.ScriptTarget.ESNext)
        )
    const makeArrExpr = (dict) =>
        printer.printNode(
            ts.EmitHint.Unspecified,
            ts.factory.createArrayLiteralExpression(
                Object.keys(dict)
                    .sort()
                    .map((k) => dict[k])
            ),
            ts.createSourceFile('', '', ts.ScriptTarget.ESNext)
        )

    const manifestScenes = makeObjExpr(scenes)
    const manifestSceneCfg = makeObjExpr(sceneConfigs)
    const manifestRoutes = makeObjExpr(routes)
    const manifestRedirects = makeObjExpr(redirects)
    const manifestUrls = makeObjExpr(urls)
    const manifestFileSystemTypes = makeObjExpr(fileSystemTypes.sort((a, b) => a.name.text.localeCompare(b.name.text)))
    const manifestTreeItemsNew = makeArrExpr(treeItemsNew)
    const manifestTreeItemsProducts = makeArrExpr(treeItemsProducts)
    const manifestTreeItemsGames = makeArrExpr(treeItemsGames)
    const manifestTreeItemsMetadata = makeArrExpr(treeItemsMetadata)

    // ───────────────────────────────────
    // 4. Harvest *all* imports from ASTs
    // ───────────────────────────────────
    const gathered = {}
    const globalNames = new Set()

    const addImport = (mod, kind, spec) => {
        // Klutch
        if (mod === './types' && spec === 'ProductManifest') {
            return
        }

        if (!gathered[mod]) {
            gathered[mod] = { default: null, namespace: null, named: new Set(), typeNamed: new Set() }
        }
        const entry = gathered[mod]

        const localName =
            kind === 'default'
                ? spec
                : kind === 'namespace'
                ? spec
                : spec.includes(' as ')
                ? spec.split(' as ').pop()
                : spec
        if (globalNames.has(localName)) {
            return
        }
        globalNames.add(localName)

        if (kind === 'default') {
            entry.default = spec
        } else if (kind === 'namespace') {
            entry.namespace = spec
        } else if (kind === 'named') {
            entry.named.add(spec)
        } else {
            entry.typeNamed.add(spec)
        }
    }

    for (const manifestPath of sourceFiles) {
        const sf = program.getSourceFile(manifestPath)
        sf.statements.filter(ts.isImportDeclaration).forEach((decl) => {
            if (!ts.isStringLiteral(decl.moduleSpecifier)) {
                return
            }
            const rawModule = decl.moduleSpecifier.text
            const modulePath = rawModule.startsWith('.')
                ? path
                      .relative(path.resolve(__dirname, 'src'), path.resolve(path.dirname(manifestPath), rawModule))
                      .replace(/^[^.]/, (m) => `./${m}`)
                : rawModule

            const ic = decl.importClause
            if (!ic) {
                return
            }
            if (ic.name) {
                addImport(modulePath, 'default', ic.name.text)
            }

            const pushSpecifiers = (list, typeOnly) => {
                list.forEach((n) => {
                    const original = n.propertyName ? n.propertyName.text : n.name.text
                    const local = n.name.text
                    const alias = original === local ? original : `${original} as ${local}`
                    addImport(modulePath, typeOnly ? 'typeNamed' : 'named', alias)
                })
            }

            if (ic.namedBindings) {
                if (ts.isNamespaceImport(ic.namedBindings)) {
                    addImport(modulePath, 'namespace', ic.namedBindings.name.text)
                } else if (ts.isNamedImports(ic.namedBindings)) {
                    pushSpecifiers(ic.namedBindings.elements, ic.isTypeOnly)
                }
            }
        })
    }

    // Ensure critical helpers are always present
    if (!globalNames.has('Params')) {
        addImport('scenes/sceneTypes', 'typeNamed', 'Params')
    }
    if (!globalNames.has('FileSystemImport')) {
        addImport('~/queries/schema/schema-general', 'typeNamed', 'FileSystemImport')
    }

    // ──────────────────────────────────────────────────────
    // 5. Serialise gathered imports → valid TypeScript code
    //    (no duplicate names, type/value kept separate)
    // ──────────────────────────────────────────────────────
    const importLines = Object.entries(gathered)
        .flatMap(([mod, spec]) => {
            const lines = []
            const named = [...spec.named].sort()
            const typeNamed = [...spec.typeNamed].sort()

            // value imports
            if (spec.namespace) {
                const head = spec.default
                    ? `import ${spec.default}, * as ${spec.namespace} from '${mod}';`
                    : `import * as ${spec.namespace} from '${mod}';`
                lines.push(head)
                if (named.length) {
                    lines.push(`import { ${named.join(', ')} } from '${mod}';`)
                }
            } else {
                if (spec.default && named.length) {
                    lines.push(`import ${spec.default}, { ${named.join(', ')} } from '${mod}';`)
                } else if (spec.default) {
                    lines.push(`import ${spec.default} from '${mod}';`)
                } else if (named.length) {
                    lines.push(`import { ${named.join(', ')} } from '${mod}';`)
                }
            }

            // type-only imports
            if (typeNamed.length) {
                lines.push(`import type { ${typeNamed.join(', ')} } from '${mod}';`)
            }
            return lines
        })
        .sort()
        .join('\n')

    // ────────────────────────────
    // 6. Assemble `products.tsx`
    // ────────────────────────────
    const autogen = '/** This const is auto-generated, as is the whole file */'
    const productsTsx = `
        /* eslint @typescript-eslint/explicit-module-boundary-types: 0 */
        // Generated by utils-gatherProductManifests.mjs – DO NOT EDIT BY HAND.

        ${importLines}

        ${autogen}
        export const productScenes: Record<string, () => Promise<any>> = ${manifestScenes}

        ${autogen}
        export const productRoutes: Record<string, [string, string]> = ${manifestRoutes}

        ${autogen}
        export const productRedirects: Record<string, string | ((params: Params, searchParams: Params, hashParams: Params) => string)> = ${manifestRedirects}

        ${autogen}
        export const productConfiguration: Record<string, any> = ${manifestSceneCfg}

        ${autogen}
        export const productUrls = ${manifestUrls}

        ${autogen}
        export const fileSystemTypes = ${manifestFileSystemTypes}

        ${autogen}
        export const getTreeItemsNew = (): FileSystemImport[] => ${manifestTreeItemsNew}

        ${autogen}
        export const getTreeItemsProducts = (): FileSystemImport[] => ${manifestTreeItemsProducts}

        ${autogen}
        export const getTreeItemsGames = (): FileSystemImport[] => ${manifestTreeItemsGames}

        ${autogen}
        export const getTreeItemsMetadata = (): FileSystemImport[] => ${manifestTreeItemsMetadata}
    `

    // ─────────────────────────────
    // 7. Write, format, move to src/
    // ─────────────────────────────
    const tmpDir = path.join(__dirname, 'tmp')
    fse.mkdirSync(tmpDir, { recursive: true })
    const tmpFile = path.join(tmpDir, 'products.tsx')
    fse.writeFileSync(tmpFile, productsTsx)
    ps.execFileSync('prettier', ['--write', tmpFile])
    fse.renameSync(tmpFile, path.join(__dirname, 'src/products.tsx'))

    // ─────────────────────────────
    // 8. Helper fns (inline)
    // ─────────────────────────────
    function keepOnlyImport(prop, manifestPath) {
        if (!ts.isPropertyAssignment(prop) || !ts.isObjectLiteralExpression(prop.initializer)) {
            return null
        }
        const imp = prop.initializer.properties.find((p) => p.name?.text === 'import')
        if (!imp) {
            return null
        }
        const fn = cloneNode(imp.initializer)
        if (
            ts.isFunctionLike(fn) &&
            ts.isCallExpression(fn.body) &&
            fn.body.arguments.length === 1 &&
            ts.isStringLiteralLike(fn.body.arguments[0])
        ) {
            const importText = fn.body.arguments[0].text
            if (importText.startsWith('./')) {
                const newPath = path.relative('./src/', path.join(path.dirname(manifestPath), importText))
                fn.body.arguments[0] = ts.factory.createStringLiteral(newPath)
            }
            return ts.factory.createPropertyAssignment(prop.name, fn)
        }
        return null
    }

    function withoutImport(prop) {
        if (!ts.isPropertyAssignment(prop) || !ts.isObjectLiteralExpression(prop.initializer)) {
            return null
        }
        const clone = cloneNode(prop)
        clone.initializer.properties = clone.initializer.properties.filter((p) => p.name?.text !== 'import')
        return clone
    }
}
