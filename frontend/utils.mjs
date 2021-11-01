import { sassPlugin as _sassPlugin } from 'esbuild-sass-plugin'
import { createImporter } from 'sass-extended-importer'
import { lessLoader } from 'esbuild-plugin-less'
import * as path from 'path'
import * as url from 'url'
import * as fs from 'fs'
import * as fse from 'fs-extra'
import { build } from 'esbuild'
import chokidar from 'chokidar'
import liveServer from 'live-server'
import { createProxyMiddleware } from 'http-proxy-middleware'

const defaultHost = process.argv.includes('--host') && process.argv.includes('0.0.0.0') ? '0.0.0.0' : 'localhost'
const defaultPort = 8234
const defaultBackend = 'http://localhost:8000'

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

export function copyIndexHtml(from = 'src/index.html', to = 'dist/index.html', entry = 'index') {
    fs.writeFileSync(
        path.resolve(__dirname, to),
        fs
            .readFileSync(path.resolve(__dirname, from), { encoding: 'utf-8' })
            .replace(
                '</head>',
                `<script type="module" src="${isDev ? jsURL : ''}/static/${entry}.js"></script>\n` +
                    `<link rel="stylesheet" href='${isDev ? jsURL : ''}/static/${entry}.css'>\n</head>`
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
    metafile: isDev,
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
    const filename = path.resolve(__dirname, 'tmp', 'reload.txt')
    fs.mkdirSync(path.dirname(filename), { recursive: true })
    fs.closeSync(fs.openSync(filename, 'w'))
}

export async function buildOrWatch(config) {
    const { name, onBuildStart, onBuildComplete, ..._config } = config

    let buildPromise = null
    let buildAgain = false
    let inputFiles = new Set([])

    async function debouncedBuild() {
        if (buildPromise) {
            buildAgain = true
            return
        }
        buildAgain = false
        onBuildStart?.()
        reloadLiveServer()
        buildPromise = runBuild()
        await buildPromise
        buildPromise = null
        onBuildComplete?.()
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
    const backend = opts.backend || defaultBackend
    const backendUrls = opts.backendUrls || [
        '/_',
        '/admin/',
        '/api/',
        '/authorize_and_redirect/',
        '/batch/',
        '/capture/',
        '/decide/',
        '/demo',
        '/e/',
        '/engage/',
        '/login',
        '/logout',
        '/s/',
        '/signup/finish/',
        '/static/recorder.js',
        '/static/rest_framework/',
        '/track/',
    ]

    const INJECTED_CODE = fs.readFileSync(
        path.join(__dirname, '..', 'node_modules', 'live-server', 'injected.html'),
        'utf8'
    )
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
                    await new Promise((r) => setTimeout(r, 400))
                }
                next()
            },
            createProxyMiddleware((pathname) => !!backendUrls.find((u) => pathname.startsWith(u)), {
                target: backend,
                changeOrigin: true,
                logLevel: 'warn',
            }),
            createProxyMiddleware(
                (pathname, req) => {
                    return !pathname.startsWith('/static/') && req.headers.accept.includes('html')
                },
                {
                    target: backend,
                    bypass: () => '/',
                    logLevel: 'warn',
                    changeOrigin: true,
                    selfHandleResponse: true, // so that the onProxyRes takes care of sending the response
                    onError: (err, req, res) => {
                        res.writeHead(500, {
                            'Content-Type': 'text/html',
                        })
                        res.end(
                            `Can not access <a href="${backend}">${backend}</a>. Is the PostHog Django app running?`
                        )
                    },
                    onProxyRes: (proxyRes, req, res) => {
                        let body = new Buffer('')
                        proxyRes.on('data', (data) => {
                            body = Buffer.concat([body, data])
                        })
                        proxyRes.on('end', () => {
                            const newBody = body.toString('utf-8').replace('</body>', INJECTED_CODE + '</body>')
                            res.end(Buffer.from(newBody, 'utf-8'))
                        })
                    },
                }
            ),
        ],
    })
    return {
        pauseServer,
        resumeServer,
    }
}
