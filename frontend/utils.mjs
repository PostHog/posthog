import { sassPlugin as _sassPlugin } from 'esbuild-sass-plugin'
import { createImporter } from 'sass-extended-importer'
import { lessLoader } from 'esbuild-plugin-less'
import * as path from 'path'
import * as url from 'url'
import express from 'express'
import cors from 'cors'
import fse from 'fs-extra'
import { build } from 'esbuild'
import chokidar from 'chokidar'

const defaultHost = process.argv.includes('--host') && process.argv.includes('0.0.0.0') ? '0.0.0.0' : 'localhost'
const defaultPort = 8234

export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
export const isDev = process.argv.includes('--dev')

const useJsURL = Boolean(process.env.JS_URL) || isDev
const jsURL = process.env.JS_URL || `http://${defaultHost}:${defaultPort}`

export const sassPlugin = _sassPlugin({
    importer: [
        (importUrl) => {
            const [first, ...rest] = importUrl.split('/')
            const paths = {
                '~': 'src',
                scenes: 'src/scenes',
                public: 'public',
                'react-toastify': '../node_modules/react-toastify',
            }
            if (paths[first]) {
                return {
                    file: path.resolve(__dirname, paths[first], ...rest),
                }
            }
        },
        createImporter(),
    ],
})

export const lessPlugin = lessLoader({ javascriptEnabled: true })

export function copyPublicFolder() {
    const srcDir = path.resolve(__dirname, 'public')
    const destDir = path.resolve(__dirname, 'dist')

    fse.copySync(srcDir, destDir, { overwrite: true }, function (err) {
        if (err) {
            console.error(err)
        }
    })
}

export function copyIndexHtml(
    from = 'src/index.html',
    to = 'dist/index.html',
    entry = 'index',
    chunks = {},
    entrypoints = []
) {
    const buildId = new Date().valueOf()

    const relativeFiles = entrypoints.map((e) => path.relative(path.resolve(__dirname, 'dist'), e))
    const jsFile =
        relativeFiles.length > 0 ? `"${relativeFiles.find((e) => e.endsWith('.js'))}"` : `"${entry}.js?t=${buildId}"`
    const cssFile =
        relativeFiles.length > 0 ? `${relativeFiles.find((e) => e.endsWith('.css'))}` : `${entry}.css?t=${buildId}`

    const scriptCode = `
        window.ESBUILD_LOAD_SCRIPT = async function (file) {
            try {
                await import('${useJsURL ? jsURL : ''}/static/' + file)
            } catch (error) {
                console.error('Error loading chunk: "' + file + '"')
                console.error(error)
            }
        }
        window.ESBUILD_LOAD_SCRIPT(${jsFile})
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

    const cssLinkTag = cssFile ? `<link rel="stylesheet" href='${useJsURL ? jsURL : ''}/static/${cssFile}'>` : ''

    fse.writeFileSync(
        path.resolve(__dirname, to),
        fse.readFileSync(path.resolve(__dirname, from), { encoding: 'utf-8' }).replace(
            '</head>',
            `   <script type="application/javascript">
                    ${scriptCode}
                    ${Object.keys(chunks).length > 0 ? chunkCode : ''}
                </script>
                ${cssLinkTag}
            </head>`
        )
    )
}

/** Makes copies: "index-TMOJQ3VI.js" -> "index.js" */
export function createHashlessEntrypoints(entrypoints) {
    for (const entrypoint of entrypoints) {
        const withoutHash = entrypoint.replace(/-([A-Z0-9]+).(js|css)$/, '.$2')
        fse.writeFileSync(path.resolve(withoutHash), fse.readFileSync(path.resolve(entrypoint)))
    }
}

export const commonConfig = {
    sourcemap: true,
    incremental: isDev,
    minify: !isDev,
    resolveExtensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
    publicPath: '/static',
    assetNames: 'assets/[name]-[hash]',
    chunkNames: '[name]-[hash]',
    entryNames: '[dir]/[name]-[hash]',
    plugins: [sassPlugin, lessPlugin],
    define: {
        global: 'globalThis',
        'process.env.NODE_ENV': isDev ? '"development"' : '"production"',
    },
    loader: {
        '.png': 'file',
        '.svg': 'file',
        '.woff': 'file',
        '.woff2': 'file',
        '.mp3': 'file',
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
            (i) => i.kind === 'import-statement' && i.path.startsWith('frontend/dist/chunk-')
        )
        const exports = output.exports.filter((e) => e !== 'default' && e !== 'scene')
        if (importStatements.length > 0 && (exports.length > 0 || output.entryPoint === 'frontend/src/index.tsx')) {
            chunks[exports[0] || 'index'] = importStatements.map((i) =>
                i.path.replace('frontend/dist/chunk-', '').replace('.js', '')
            )
        }
    }
    return chunks
}

export async function buildInParallel(configs, { onBuildStart, onBuildComplete }) {
    await Promise.all(
        configs.map((config) =>
            buildOrWatch({
                ...config,
                onBuildStart,
                onBuildComplete,
            })
        )
    )
}

/** Get the main ".js" and ".css" files for a build */
function getBuiltEntryPoints(config, result) {
    let outfiles = []
    if (config.outdir) {
        // convert "src/index.tsx" --> /a/posthog/frontend/dist/index.js
        outfiles = config.entryPoints.map((file) =>
            path
                .resolve(__dirname, file)
                .replace('/src/', '/dist/')
                .replace(/\.[^\.]+$/, '.js')
        )
    } else if (config.outfile) {
        outfiles = [config.outfile]
    }

    const builtFiles = []
    for (const outfile of outfiles) {
        // convert "/a/something.tsx" --> "/a/something-"
        const searchString = `${outfile.replace(/\.[^/]+$/, '')}-`
        // find if we built a .js or .css file that matches
        for (const file of Object.keys(result.metafile.outputs)) {
            const absoluteFile = path.resolve(process.cwd(), file)
            if (absoluteFile.startsWith(searchString) && (file.endsWith('.js') || file.endsWith('.css'))) {
                builtFiles.push(absoluteFile)
            }
        }
    }

    return builtFiles
}

export async function buildOrWatch(config) {
    const { name, onBuildStart, onBuildComplete, ..._config } = config

    let buildPromise = null
    let buildAgain = false
    let inputFiles = new Set([])

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
        onBuildStart?.(config)
        reloadLiveServer()
        buildPromise = runBuild()
        const buildResponse = await buildPromise
        buildPromise = null
        onBuildComplete?.(config, buildResponse)
        if (isDev && buildAgain) {
            void debouncedBuild()
        }
    }

    let result = null
    let buildCount = 0

    async function runBuild() {
        buildCount++
        const time = new Date()
        if (buildCount === 1) {
            console.log(`🧱 Building${name ? ` "${name}"` : ''}`)
            try {
                result = await build({ ...commonConfig, ..._config })
                console.log(`🥇 Built${name ? ` "${name}"` : ''} in ${(new Date() - time) / 1000}s`)
            } catch (error) {
                console.log(`🛑 Building${name ? ` "${name}"` : ''} failed in ${(new Date() - time) / 1000}s`)
                process.exit(1) // must exit since with result === null, result.rebuild() won't work
            }
        } else {
            try {
                result = await result.rebuild()
                console.log(`🔄 Rebuilt${name ? ` "${name}"` : ''} in ${(new Date() - time) / 1000}s`)
            } catch (e) {
                console.log(`🛑 Rebuilding${name ? ` "${name}"` : ''} failed in ${(new Date() - time) / 1000}s`)
            }
        }
        inputFiles = getInputFiles(result)

        return {
            chunks: getChunks(result),
            entrypoints: getBuiltEntryPoints(config, result),
        }
    }

    if (isDev) {
        chokidar
            .watch(path.resolve(__dirname, 'src'), {
                ignored: /.*(Type|\.test\.stories)\.[tj]sx$/,
                ignoreInitial: true,
            })
            .on('all', async (event, filePath) => {
                if (inputFiles.size === 0) {
                    await buildPromise
                }
                if (inputFiles.has(filePath)) {
                    void debouncedBuild()
                }
            })
    }

    await debouncedBuild()
}

let clients = new Set()

function reloadLiveServer() {
    clients.forEach((client) => client.write(`data: reload\n\n`))
}

export function startServer(opts = {}) {
    const host = opts.host || defaultHost
    const port = opts.port || defaultPort

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
            const filePath = path.resolve(__dirname, 'dist', pathFromUrl)
            // protect against "/../" urls
            if (filePath.startsWith(path.resolve(__dirname, 'dist'))) {
                res.sendFile(filePath.split('?')[0])
                return
            }
        }
        res.sendFile(path.resolve(__dirname, 'dist', 'index.html'))
    })
    app.listen(port)

    return {
        pauseServer,
        resumeServer,
    }
}
