import { build } from 'esbuild'
import * as path from 'node:path'

// esbuild puts every stylesheet reachable from an entry point into that entry's CSS file, even
// through `import()` boundaries, so a feature's CSS ships on the boot path as long as JS imports
// it. These plugins take a stylesheet out of the JS graph and hand the code a URL instead, so the
// component attaches the sheet when it renders (see frontend/src/lib/utils/lazyStylesheet.ts).

const URL_SUFFIX = '?url'
const NAMESPACE = 'lazy-stylesheet'

/**
 * `import href from './Feature.scss?url'` bundles that stylesheet into its own hashed file under
 * `<outdir>/stylesheets/` and evaluates to its URL under `JS_URL/static/`, like the chunk loader
 * does. The nested build reuses the importing build's options, so sass, Tailwind and font
 * loaders behave the same as in the boot stylesheet. Vite supports `?url` natively.
 */
export function lazyStylesheetPlugin({ hashed }) {
    return {
        name: 'lazy-stylesheet',
        setup(build_) {
            build_.onResolve({ filter: /\.(css|scss)\?url$/ }, async (args) => {
                const resolved = await build_.resolve(args.path.slice(0, -URL_SUFFIX.length), {
                    kind: args.kind,
                    importer: args.importer,
                    resolveDir: args.resolveDir,
                })
                if (resolved.errors.length > 0) {
                    return { errors: resolved.errors }
                }
                return { path: resolved.path, namespace: NAMESPACE }
            })

            build_.onLoad({ filter: /.*/, namespace: NAMESPACE }, async (args) => {
                const options = build_.initialOptions
                const workingDir = options.absWorkingDir ?? process.cwd()
                const outdir = options.outdir ?? path.dirname(path.resolve(workingDir, options.outfile))
                const { entryPoints, stdin, outfile, splitting, format, globalName, ...inherited } = options
                const result = await build({
                    ...inherited,
                    entryPoints: [args.path],
                    outdir,
                    entryNames: hashed ? 'stylesheets/[name]-[hash]' : 'stylesheets/[name]',
                    bundle: true,
                    write: true,
                    metafile: true,
                })
                const output = Object.keys(result.metafile.outputs).find((file) => file.endsWith('.css'))
                const publicName = path.relative(outdir, path.resolve(workingDir, output)).split(path.sep).join('/')
                const realFileInputs = Object.keys(result.metafile.inputs).filter((file) => !/^[\w-]+:/.test(file))
                return {
                    contents: `export default (window.JS_URL || '') + '/static/' + ${JSON.stringify(publicName)}`,
                    loader: 'js',
                    watchFiles: realFileInputs.map((file) => path.resolve(workingDir, file)),
                }
            })
        },
    }
}

/**
 * monaco-editor's ESM modules import their own ~100 CSS files, which would otherwise land in the
 * boot stylesheet of every build that can reach monaco. Resolve them to empty CSS here;
 * frontend/src/lib/monaco/monacoStylesheet.css bundles the same files as one lazy stylesheet.
 */
export function stubMonacoCssPlugin() {
    return {
        name: 'stub-monaco-css',
        setup(build_) {
            build_.onResolve({ filter: /\.css$/ }, (args) =>
                args.importer.includes(`${path.sep}monaco-editor${path.sep}`)
                    ? { path: args.path, namespace: 'stub-monaco-css' }
                    : undefined
            )
            build_.onLoad({ filter: /.*/, namespace: 'stub-monaco-css' }, () => ({ contents: '', loader: 'css' }))
        },
    }
}
