import * as fs from 'fs'
import * as path from 'path'

import { commonConfig, copyRRWebWorkerFiles, createHashlessEntrypoints, esbuildBuild, isDev } from '@posthog/esbuilder'

// `TOOLBAR_PUBLIC_PATH`, when set, overrides the default `publicPath` so the
// toolbar bundle and its assets can be hosted under a versioned, content-pinned
// URL on the posthog-js CDN. Used by posthog-js's release workflow to ship a
// fully self-contained toolbar bundle. When unset, behaviour is unchanged from
// before this knob existed (Django-served `https://us.posthog.com/static/`).
//
// esbuild uses this verbatim as a URL prefix, so a trailing slash is required;
// add one if the caller forgot.
const toolbarPublicPathOverride = process.env.TOOLBAR_PUBLIC_PATH
    ? process.env.TOOLBAR_PUBLIC_PATH.endsWith('/')
        ? process.env.TOOLBAR_PUBLIC_PATH
        : process.env.TOOLBAR_PUBLIC_PATH + '/'
    : ''

// Modules replaced with lightweight kea logic shims that satisfy connect() contracts
// without side effects. If the upstream logic adds new connect() values, the shim
// will silently return undefined — keep shims in sync when connect contracts change.
const shimmedModules = {
    'scenes/userLogic': 'src/toolbar/shims/userLogic.ts',
    'scenes/organization/membersLogic': 'src/toolbar/shims/membersLogic.ts',
    'scenes/sceneLogic': 'src/toolbar/shims/sceneLogic.ts',
    'scenes/teamLogic': 'src/toolbar/shims/teamLogic.ts',
    'lib/logic/featureFlagLogic': 'src/toolbar/shims/featureFlagLogic.ts',
    // Hoggie illustrations are decorative; the shim renders null so no PNG assets or image
    // requests reach the toolbar bundle that runs on customer sites (asset URLs are CSP-relevant).
    'lib/brand/hoggies': 'src/toolbar/shims/hoggies.tsx',
    // Not a kea shim: the toolbar's parity-tested urls duplicate (see src/toolbar/urls.ts).
    // Toolbar code imports it directly; this entry covers lib/ components shared with the
    // app (TZLabel, Link, HeatmapEventsPanel), whose scenes/urls import would otherwise pull
    // every product manifest into the bundle.
    'scenes/urls': 'src/toolbar/urls.ts',
}

// Modules replaced with an inert proxy that logs access in debug mode
const deniedPaths = [
    '~/lib/hooks/useUploadFiles',
    '~/queries/nodes/InsightViz/InsightViz',
    'lib/hog',
    'lib/api',
    'scenes/activity/explore/EventDetails',
    'scenes/web-analytics/WebAnalyticsDashboard',
    'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager.ts',
]

// Heavy third-party libraries the toolbar never renders, but which leak in transitively
// through the shared scene graph (mostly via scenes/urls.ts -> products.tsx). Code splitting
// would defer the lazily-`import()`-ed ones rather than inline them, but until their import
// edges are cut at the source (.agents/toolbar-migration.md), denying them at resolve time
// keeps them out of the artifact set entirely — bin/check-toolbar-graph.mjs asserts absence.
const deniedThirdPartyPackages = [
    // mermaid diagram rendering (via LemonMarkdownWithMermaid). Denying the entry cascades to
    // its exclusive deps: katex, cytoscape, @mermaid-js/parser, dagre-d3-es, layout/cose-base.
    /^mermaid(\/|$)/,
    // chart.js + its annotation plugin (via Sparkline). Charts in the toolbar go through the
    // already-denied LineGraph.
    /^chart\.js(\/|$)/,
    /^chartjs-plugin-annotation(\/|$)/,
    // hls.js needs no deny anymore: its only path in was @posthog/replay-shared, whose last
    // importer (~/types' SnapshotSourceType value re-export) is now type-only. Reintroduction
    // is caught by FORBIDDEN_PACKAGES in bin/check-toolbar-graph.mjs.
]

const deniedPatterns = [
    /monaco/,
    /scenes\/insights\/filters\/ActionFilter/,
    /lib\/components\/CodeSnippet/,
    /scenes\/session-recordings\/player/,
    /queries\/schema-guard/,
    /queries\/schema.json/,
    /queries\/QueryEditor\/QueryEditor/,
    /scenes\/billing/,
    /scenes\/data-warehouse/,
    /LineGraph/,
    ...deniedThirdPartyPackages,
]

/**
 * The toolbar includes many parts of the main posthog app,
 * but we don't want to include everything in the toolbar bundle.
 * Partly because it would be too big, and partly because some things
 * in the main app cause problems for people using CSPs on their sites.
 *
 * It wasn't possible to tree-shake the dependencies out of the bundle,
 * and we don't want to change the app code significantly just for the toolbar.
 *
 * So instead we replace some imports in the toolbar:
 * - Shimmed modules get swapped for lightweight kea logics (needed by connect())
 * - Denied modules get replaced with an inert proxy
 */
function createToolbarModulePlugin(dirname) {
    // Shims must also catch relative imports of the same modules (e.g. dataThemeLogic's
    // `./teamLogic`), otherwise the real logic and its whole app graph leak into the bundle.
    // Map each shimmed module's extensionless absolute path to its shim.
    const shimsByAbsolutePath = new Map(
        Object.entries(shimmedModules).map(([alias, shimFile]) => [
            path.resolve(dirname, 'src', alias),
            path.resolve(dirname, shimFile),
        ])
    )
    return {
        name: 'toolbar-module-replacements',
        setup(build) {
            build.onResolve({ filter: /.*/ }, (args) => {
                const shimFile = shimmedModules[args.path] ?? shimmedModules[args.path.replace(/^~\//, '')]
                if (shimFile) {
                    return { path: path.resolve(dirname, shimFile) }
                }

                if (args.path.startsWith('.') && args.importer) {
                    const absolute = path
                        .resolve(path.dirname(args.importer), args.path)
                        .replace(/\.(tsx|ts|jsx|js)$/, '')
                    const shimPath = shimsByAbsolutePath.get(absolute)
                    if (shimPath) {
                        return { path: shimPath }
                    }
                }

                const shouldDeny =
                    deniedPaths.includes(args.path) || deniedPatterns.some((pattern) => pattern.test(args.path))
                if (shouldDeny) {
                    return { path: args.path, namespace: 'empty-module', sideEffects: false }
                }
            })

            build.onLoad({ filter: /.*/, namespace: 'empty-module' }, (args) => {
                return {
                    contents: `
                        module.exports = new Proxy({}, {
                            get: function(target, prop) {
                                // Prevent proxy from being treated as a Promise (thenable detection)
                                if (prop === 'then') return undefined;
                                // Tell bundler this is a CommonJS module, not ESM
                                if (prop === '__esModule') return false;
                                const shouldLog = window && window.posthog && window.posthog.config && window.posthog.config.debug;
                                if (shouldLog) {
                                    console.warn('[TOOLBAR] Attempted to use denied module:', ${JSON.stringify(
                                        args.path
                                    )});
                                }
                                return function() {
                                    return {}
                                }
                            }
                        });
                    `,
                    loader: 'js',
                }
            })
        },
    }
}

// The toolbar ships as two artifacts (see .agents/toolbar-migration.md):
//
//   dist/toolbar.js          — a tiny classic-script loader (src/toolbar/loader.ts). posthog-js
//                              injects it with a plain <script> tag on customer pages and calls
//                              window.ph_load_toolbar on load; the loader then import()s the app.
//   dist/toolbar/            — the real app: an ESM entry (toolbar-app-<hash>.js, hashless copy
//                              alongside as a version-skew fallback) plus code-split chunks, so
//                              lazily-imported features are fetched on demand instead of inlined.
//   dist/toolbar/toolbar-app.css — the app entry's stylesheet (hashless copy); ToolbarApp.tsx
//                              fetches it into the shadow root. It lives inside dist/toolbar/
//                              so its relative font url()s resolve against toolbar/assets/.
//   dist/toolbar.css         — copy at the old URL, only consumed by stale-cached single-file
//                              toolbar.js builds during the unversioned-deploy transition window.
//
// The loader resolves the app relative to its own script URL, and chunk imports inside the app
// are relative too, so the same artifacts work from Django /static/ on any instance and from
// the versioned/major-alias/compatibility prefixes on the posthog-js CDN (whose release
// pipeline publishes dist/toolbar/ recursively when present).

export function getToolbarAppBuildConfig(dirname) {
    return {
        // Named 'Toolbar' so the metafile lands at toolbar-esbuild-meta.json, which
        // bin/check-toolbar-graph.mjs and bin/check-toolbar-size.mjs read.
        name: 'Toolbar',
        entryPoints: { 'toolbar-app': 'src/toolbar/index.tsx' },
        format: 'esm',
        splitting: true,
        outdir: path.resolve(dirname, 'dist', 'toolbar'),
        chunkNames: 'chunk-[name]-[hash]',
        // Shadow any AMD loader on the host page (module-scoped var, applied to every output
        // file) so bundled UMD dependencies don't try to register with e.g. RequireJS.
        banner: { js: 'var define = undefined;' },
        // NO publicPath (explicitly overriding commonConfig's '/static'): esbuild would bake it
        // into the chunk import specifiers as absolute URLs, but the same artifacts are served
        // from Django /static/ on any region or self-hosted instance and from the posthog-js
        // CDN prefixes — chunks must resolve relative to the importing module. Fonts stay
        // file-loaded with relative url()s in the CSS (which is fetched from inside
        // dist/toolbar/, so they resolve); svgs are imported from JS where a relative specifier
        // string would resolve against the customer page's URL, so inline them instead.
        publicPath: undefined,
        loader: { ...commonConfig.loader, '.svg': 'dataurl' },
        // Inject TOOLBAR_PUBLIC_PATH at build time as a bare global so runtime
        // code (e.g. ToolbarApp.tsx's CSS loader) can construct URLs to sibling
        // files in the same versioned bundle. The identifier is declared as
        // `declare const` in frontend/src/globals.d.ts so TypeScript is happy.
        // Merge with commonConfig.define so we don't drop the inherited
        // `global` / `process.env.NODE_ENV` substitutions.
        define: {
            ...commonConfig.define,
            __POSTHOG_TOOLBAR_PUBLIC_PATH__: JSON.stringify(toolbarPublicPathOverride),
        },
        writeMetaFile: true,
        extraPlugins: [createToolbarModulePlugin(dirname)],
    }
}

/**
 * Runs after the toolbar app build: emits the hashless entry copies, promotes the entry CSS to
 * the stable dist/toolbar.css URL, and builds the loader with the hashed entry filename baked
 * in. Called from build.mjs's onBuildComplete and bin/build-toolbar.mjs (including per rebuild
 * in watch mode — the loader build is a single tiny file).
 */
export async function finalizeToolbarBuild(dirname, buildResponse) {
    if (!buildResponse) {
        return
    }

    const entrypoints = buildResponse.entrypoints || []
    const entryJs = entrypoints.find((e) => e.endsWith('.js'))
    const entryCss = entrypoints.find((e) => e.endsWith('.css'))
    if (!entryJs || !entryCss) {
        // Failing the build beats shipping a loader that points at nothing.
        throw new Error(`Toolbar app build produced no entry ${!entryJs ? 'JS' : 'CSS'} output.`)
    }

    // esbuild emits per-chunk CSS: only the entry's stylesheet is loaded into the shadow root
    // (as toolbar.css), so toolbar features must keep their styles statically imported. Chunk
    // CSS files are dead weight from lazily-imported app scenes, not a correctness problem.

    // toolbar-app-<hash>.js -> toolbar-app.js next to it: the loader's version-skew fallback.
    createHashlessEntrypoints(dirname, entrypoints)
    // The copy lives one directory up from the entry CSS, so point its sourceMappingURL back
    // into dist/toolbar/ — collectstatic fails on a sourcemap reference it can't resolve.
    const entryCssContent = fs
        .readFileSync(entryCss, 'utf8')
        .replace(/sourceMappingURL=([^\s*]+\.css\.map)/, 'sourceMappingURL=toolbar/$1')
    fs.writeFileSync(path.resolve(dirname, 'dist', 'toolbar.css'), entryCssContent)

    // The chunks bundle rrweb, whose inlined worker string carries a sourceMappingURL that
    // collectstatic resolves relative to dist/toolbar/ — the map must exist there too.
    copyRRWebWorkerFiles(dirname, 'dist/toolbar')

    await esbuildBuild({
        absWorkingDir: dirname,
        entryPoints: ['src/toolbar/loader.ts'],
        bundle: true,
        // ESM output keeps the runtime-dynamic import() untouched; with no static
        // imports/exports of its own, the file still parses as a classic script.
        format: 'esm',
        outfile: path.resolve(dirname, 'dist', 'toolbar.js'),
        minify: !isDev,
        sourcemap: true,
        target: commonConfig.target,
        tsconfig: commonConfig.tsconfig,
        define: {
            ...commonConfig.define,
            __POSTHOG_TOOLBAR_PUBLIC_PATH__: JSON.stringify(toolbarPublicPathOverride),
            __POSTHOG_TOOLBAR_APP_ENTRY__: JSON.stringify(path.basename(entryJs)),
        },
    })
}
