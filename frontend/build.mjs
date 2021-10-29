import { build } from 'esbuild'
import { sassPlugin } from 'esbuild-sass-plugin'
import { createImporter } from 'sass-extended-importer'
import { lessLoader } from 'esbuild-plugin-less'
import * as path from 'path'
import * as url from 'url'
import * as fs from 'fs'

const __dirname = path.dirname(url.fileURLToPath(import.meta.url))

await build({
    entryPoints: ['src/index.tsx'],
    bundle: true,
    resolveExtensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
    outdir: path.resolve(__dirname, 'dist2'),
    plugins: [
        {
            name: 'alias',
            setup(build) {
                build.onResolve({ filter: /!raw-loader!@posthog\/plugin-scaffold/, namespace: 'file' }, (args) => {
                    const file = args.path.replace('!raw-loader!', path.resolve(__dirname, '..', 'node_modules') + '/')
                    return ({
                        path: file,
                        watchFiles: [file]
                    })
                })
                build.onLoad({ filter: /@posthog\/plugin-scaffold/, namespace: 'file' }, async (args) => {
                    return {
                        loader: 'text',
                        contents: fs.readFileSync(args.path, { encoding: 'utf-8'}),
                        resolveDir: path.dirname(args.path),
                    }
                })
            },
        },
        sassPlugin({
            importer: [
                (url) => {
                    const [first, ...rest] = url.split('/')
                    const paths = {
                        '~': 'src',
                        scenes: 'src/scenes',
                        public: 'public',
                        'react-toastify': '../node_modules/react-toastify',
                    }
                    // debugger
                    if (paths[first]) {
                        return {
                            file: path.resolve(__dirname, paths[first], ...rest),
                        }
                    }
                },
                createImporter(),
            ],
        }),
        lessLoader({ javascriptEnabled: true }),
    ],
    loader: {
        '.png': 'file',
        '.svg': 'file',
        '.woff': 'file',
        '.woff2': 'file',
        '.mp3': 'file',
    },
}).catch(() => process.exit(1))
