import { sassPlugin as _sassPlugin } from 'esbuild-sass-plugin'
import { createImporter } from 'sass-extended-importer'
import { lessLoader } from 'esbuild-plugin-less'
import * as path from 'path'
import * as url from 'url'
import * as fs from 'fs'
import * as fse from 'fs-extra'
import { build } from 'esbuild'
import chokidar from 'chokidar'

export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const jsURL = 'http://localhost:8234'

export const isWatch = process.argv.includes('--watch') || process.argv.includes('-w')
export const isDev = process.argv.includes('--dev') || process.argv.includes('-d')

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

    // To copy a folder or file
    fse.copySync(srcDir, destDir, { overwrite: true }, function (err) {
        if (err) {
            console.error(err) // add if you want to replace existing folder or file with same name
        } else {
            console.log('success!')
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
                `<script type="module" src="${isWatch ? jsURL : ''}/static/${entry}.js"></script>\n` +
                    `<link rel="stylesheet" href='${isWatch ? jsURL : ''}/static/${entry}.css'>\n</head>`
            )
    )
}

export const commonConfig = {
    sourcemap: true,
    incremental: isWatch,
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
    metafile: isWatch,
}

function getInputFiles(result) {
    return new Set(
        Object.keys(result.metafile.inputs)
            .map((key) => (key.includes(':') ? key.split(':')[1] : key))
            .map((key) => (key.startsWith('/') ? key : path.resolve(process.cwd(), key)))
    )
}

export async function buildOrWatch(config) {
    const { name, ..._config } = config

    let buildPromise = null
    let buildAgain = false
    let inputFiles = new Set([])

    async function debouncedBuild() {
        if (buildPromise) {
            buildAgain = true
            return
        }
        buildAgain = false
        buildPromise = runBuild()
        await buildPromise
        buildPromise = null
        if (isWatch && buildAgain) {
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
            } catch (error) {
                console.error(error)
                process.exit(1)
            }
            console.log(
                `🏁 ${isWatch ? 'First build of' : 'Built'}${name ? ` "${name}"` : ''} in ${
                    (new Date() - time) / 1000
                }s`
            )
        } else {
            result = await result.rebuild()
            console.log(`🔄 Rebuilt${name ? ` "${name}"` : ''} in ${(new Date() - time) / 1000}s`)
        }
        inputFiles = getInputFiles(result)
    }

    if (isWatch) {
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
