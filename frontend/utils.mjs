import autoprefixer from 'autoprefixer'
import cors from 'cors'
import cssnano from 'cssnano'
import esbuild from 'esbuild'
import { lessLoader } from 'esbuild-plugin-less'
import { polyfillNode } from 'esbuild-plugin-polyfill-node'
import { sassPlugin } from 'esbuild-sass-plugin'
import express from 'express'
import fse from 'fs-extra'
import path from 'path'
import { dirname } from 'path'
import postcss from 'postcss'
import postcssPresetEnv from 'postcss-preset-env'
import tailwindcss from 'tailwindcss'
import { fileURLToPath } from 'url'

const defaultHost = process.argv.includes('--host') && process.argv.includes('0.0.0.0') ? '0.0.0.0' : 'localhost'
const defaultPort = 8234

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export const isDev = process.argv.includes('--dev')

export function copyPublicFolder(srcDir, destDir) {
    fse.copySync(srcDir, destDir, { overwrite: true }, (err) => {
        if (err) {
            console.error(err)
        }
    })

    if (isDev) {
        console.log('Copied public assets to dist for development.')
    }
}

/** Update the file's modified and accessed times to now. */
export async function touchFile(file) {
    const now = new Date()
    await fse.utimes(file, now, now)
}

export function copyIndexHtml(
    absWorkingDir = '.',
    from = 'src/index.html',
    to = 'dist/index.html',
    entry = 'index',
    chunks = {},
    entrypoints = []
) {
    const buildId = new Date().valueOf()

    const relativeFiles = entrypoints.map((e) => path.relative(path.resolve(absWorkingDir, 'dist'), e))
    const jsFile = relativeFiles.length > 0 ? relativeFiles.find((e) => e.endsWith('.js')) : `${entry}.js?t=${buildId}`
    const cssFile =
        relativeFiles.length > 0 ? relativeFiles.find((e) => e.endsWith('.css')) : `${entry}.css?t=${buildId}`

    const scriptCode = `
        (() => {
            const jsUrl = window.JS_URL || '';
            const eventSource = new EventSource(jsUrl + '/esbuild');
            eventSource.onmessage = () => location.reload();
            console.log('HMR enabled via Esbuild.');
        })();
    `

    const chunkCode = `
        window.ESBUILD_LOADED_CHUNKS = new Set();
        window.ESBUILD_LOAD_CHUNKS = function(name) {
            const chunks = ${JSON.stringify(chunks)}[name] || [];
            for (const chunk of chunks) {
                if (!window.ESBUILD_LOADED_CHUNKS.has(chunk)) {
                    window.ESBUILD_LOAD_SCRIPT('chunk-' + chunk + '.js');
                    window.ESBUILD_LOADED_CHUNKS.add(chunk);
                }
            }
        };
        window.ESBUILD_LOAD_CHUNKS('index');
    `

    const cssLoader = `
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.crossOrigin = "anonymous";
        link.href = (window.JS_URL || '') + "/static/" + ${JSON.stringify(cssFile)};
        document.head.appendChild(link);
    `

    fse.writeFileSync(
        path.resolve(absWorkingDir, to),
        fse.readFileSync(path.resolve(absWorkingDir, from), { encoding: 'utf-8' }).replace(
            '</head>',
            `   <script type="application/javascript">
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
    entryNames: isDev ? '[dir]/[name]' : '[dir]/[name]-[hash]',
    plugins: [
        sassPlugin({
            async transform(source, resolveDir, filePath) {
                const plugins = [tailwindcss, autoprefixer, postcssPresetEnv({ stage: 0 })]
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

let clients = []
const contentMap = new Map()

/** Sends HMR updates to all connected clients */
function sendHMRUpdates() {
    clients.forEach((res) => res.write('data: update\n\n'))
    clients = []
}

/** Handles rebuilds and notifies clients */
function rebuildHandler(error, result) {
    if (error) {
        console.error('Error during rebuild:', error)
        return
    }

    contentMap.clear()
    for (const content of result.outputFiles) {
        contentMap.set(path.relative('.', content.path), content.text)
    }

    sendHMRUpdates()
    console.log(`Rebuilt successfully at ${new Date().toLocaleTimeString()}`)
}

/** Initialize Esbuild with HMR */
export async function initializeEsbuild() {
    const result = await esbuild.build({
        entryPoints: ['./src/index.ts'],
        bundle: true,
        outdir: 'dist',
        write: false, // Keep output in memory
        metafile: true,
        sourcemap: true,
        watch: {
            onRebuild: rebuildHandler,
        },
        banner: {
            js: `
            (() => {
                const jsUrl = window.JS_URL || '';
                const eventSource = new EventSource(jsUrl + '/esbuild');
                eventSource.onmessage = () => location.reload();
                console.log('HMR enabled via Esbuild.');
            })();
            `,
        },
    })

    rebuildHandler(null, result)
    return result
}

/** Start the dev server with HMR support */
export function startDevServer() {
    const app = express()
    app.use(cors())

    // Serve event stream for HMR
    app.get('/esbuild', (req, res) => {
        res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
        })
        clients.push(res)

        console.log(`HMR client connected: ${req.socket.remoteAddress}`)
    })

    // Serve static assets
    app.use('/static', express.static(path.resolve(__dirname, 'public')))

    // Serve files from memory or public folder
    app.get('*', (req, res) => {
        const relativePath = req.url.replace(/^\//, '')
        if (contentMap.has(relativePath)) {
            res.type('text/javascript').send(contentMap.get(relativePath))
        } else {
            const filePath = path.resolve('public', relativePath)
            if (fse.existsSync(filePath)) {
                res.sendFile(filePath)
            } else {
                res.status(404).send('File not found')
            }
        }
    })

    app.listen(defaultPort, defaultHost, () => {
        console.log(`Dev server running at http://${defaultHost}:${defaultPort}`)
    })
}

/** Main entry point */
;(async () => {
    if (isDev) {
        console.log('Starting Esbuild with HMR...')
        await initializeEsbuild()
        startDevServer()
    } else {
        console.log('Production build mode')
    }
})()
