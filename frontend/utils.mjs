import { sassPlugin as _sassPlugin } from 'esbuild-sass-plugin'
import { createImporter } from 'sass-extended-importer'
import { lessLoader } from 'esbuild-plugin-less'
import * as path from 'path'
import * as url from 'url'
import fse from 'fs-extra'
import { build } from 'esbuild'
import chokidar from 'chokidar'
import liveServer from 'live-server'

const defaultHost = process.argv.includes('--host') && process.argv.includes('0.0.0.0') ? '0.0.0.0' : 'localhost'
const defaultPort = 8234

export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const jsURL = `http://${defaultHost}:${defaultPort}`

export const isDev = process.argv.includes('--dev')

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
export function copyIndexHtml(from = 'src/index.html', to = 'dist/index.html', entry = 'index', chunks = {}) {
    const buildId = new Date().valueOf()

    fse.writeFileSync(
        path.resolve(__dirname, to),
        fse.readFileSync(path.resolve(__dirname, from), { encoding: 'utf-8' }).replace(
            '</head>',
            `   <script type="application/javascript">
                    window.ESBUILD_LOADED_CHUNKS = new Set(); 
                    window.ESBUILD_LOAD_SCRIPT = async function (file) {
                        try {
                            await import('${isDev ? jsURL : ''}/static/' + file)
                        } catch (e) {
                            console.error('Error loading chunk: "' + file + '"')
                        }
                    }
                    window.ESBUILD_LOAD_CHUNKS = function(name) { 
                        const chunks = ${JSON.stringify(chunks)}[name] || [];
                        for (const chunk of chunks) { 
                            if (!window.ESBUILD_LOADED_CHUNKS.has(chunk)) { 
                                window.ESBUILD_LOAD_SCRIPT('chunk-'+chunk+'.js'); 
                                window.ESBUILD_LOADED_CHUNKS.add(chunk);
                            } 
                        } 
                    }
                    window.ESBUILD_LOAD_SCRIPT("${entry}.js?t=" + new Date().valueOf())
                    window.ESBUILD_LOAD_CHUNKS('index');
                </script>
                <link rel="stylesheet" href='${isDev ? jsURL : ''}/static/${entry}.css?_=${buildId}'>
            </head>`
        )
    )
}

export const commonConfig = {
    sourcemap: true,
    incremental: isDev,
    minify: !isDev,
    resolveExtensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
    publicPath: '/static',
    assetNames: 'assets/[name]-[hash]',
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

function reloadLiveServer() {
    // The live-server watches just this one file, and touching it asks it to reload all files.
    // We use this file to trigger a reload as soon as we start a build, and then use a middleware
    // to pause serving the files until the build finishes. This gives improves reloads from 5sec to 3sec.
    const filename = path.resolve(__dirname, 'tmp', 'reload.txt')
    fse.mkdirSync(path.dirname(filename), { recursive: true })
    fse.closeSync(fse.openSync(filename, 'w'))
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
        onBuildStart?.()
        reloadLiveServer()
        buildPromise = runBuild()
        const chunks = await buildPromise
        buildPromise = null
        onBuildComplete?.(chunks)
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
        return getChunks(result)
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

export function startServer(opts = {}) {
    const host = opts.host || defaultHost
    const port = opts.port || defaultPort

    console.log(`🍱 Started server at http://${host}:${port}`)

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

    liveServer.start({
        port,
        host,
        root: path.resolve(__dirname, 'dist'),
        open: false,
        cors: true,
        file: 'index.html',
        mount: [['/static', path.resolve(__dirname, 'dist')]],
        watch: [path.resolve(__dirname, 'tmp', 'reload.txt')],
        logLevel: 0,
        middleware: [
            async (req, res, next) => {
                if (ifPaused && !ifPaused.logged && req.url.startsWith('/static/')) {
                    console.log('⌛️ Waiting for build to complete...')
                    ifPaused.logged = true
                    await ifPaused
                    // somehow must still delay before the static server reloads
                    // rewriting to use our own express app would solve this
                    await new Promise((r) => setTimeout(r, 400))
                }
                next()
            },
        ],
    })
    return {
        pauseServer,
        resumeServer,
    }
}
