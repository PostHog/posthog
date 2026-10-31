import { zipSync } from 'fflate'
import * as fs from 'fs'
import * as path from 'path'

import { commonConfig, copyRRWebWorkerFiles, createHashlessEntrypoints, esbuildBuild, isDev } from '@posthog/esbuilder'

// `TOOLBAR_PUBLIC_PATH`, when set, overrides the default `publicPath` so the
// toolbar bundle and its assets can be hosted under a versioned, content-pinned
// URL on the posthog-js CDN. Used by posthog-js's release workflow to ship a
// fully self-contained toolbar bundle. When unset, the bundle is served from
// Django `/static/`.
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
    'scenes/userLogic': 'src/toolbar/shared/shims/userLogic.ts',
    'models/membersLogic': 'src/toolbar/shared/shims/membersLogic.ts',
    'scenes/sceneLogic': 'src/toolbar/shared/shims/sceneLogic.ts',
    'scenes/teamLogic': 'src/toolbar/shared/shims/teamLogic.ts',
    'lib/logic/featureFlagLogic': 'src/toolbar/shared/shims/featureFlagLogic.ts',
    // Survey question labels load from an authenticated endpoint the toolbar can't reach, so
    // the shim keeps its shared consumers (PropertyKeyInfo, taxonomy helpers) out of the app zone.
    'scenes/surveys/surveyQuestionLabelsLogic': 'src/toolbar/shared/shims/surveyQuestionLabelsLogic.ts',
    // The flag overview reads the feature flags API, which the toolbar can't reach, so the shim
    // keeps PropertyKeyInfo out of the app zone.
    'products/feature_flags/frontend/featureFlagSummaryLogic': 'src/toolbar/shared/shims/featureFlagSummaryLogic.ts',
    // Not a kea shim: the toolbar's parity-tested urls duplicate (see src/toolbar/shared/urls.ts).
    // Toolbar code imports it directly; this entry covers lib/ components shared with the
    // app (TZLabel, Link, HeatmapEventsPanel), whose scenes/urls import would otherwise pull
    // every product manifest into the bundle.
    'scenes/urls': 'src/toolbar/shared/urls.ts',
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

// PayGateMini (shipped in the toolbar) imports scenes/billing, which we can't bundle because it
// pulls in chart.js, monaco, and the rest of the app's billing scene graph.
const deniedPatterns = [/scenes\/billing/]

/**
 * The toolbar shares lib/ code with the main app, and that code reaches app-only modules
 * the toolbar must not ship. Tree shaking can't drop them (the shared packages aren't marked
 * side-effect-free) and app code shouldn't contort itself for the toolbar, so imports are
 * replaced at resolve time:
 *
 * - Shimmed modules get swapped for lightweight stand-ins (kea logics satisfying connect()
 *   contracts, and the parity-tested urls duplicate). These are intentional injection points:
 *   the toolbar genuinely needs different answers (its own team context, no scene routing)
 *   than the app.
 * - Denied modules get replaced with an inert proxy. The deny list is kept minimal: only the
 *   paths a toolbar-shipped module actually reaches today (chiefly PayGateMini -> scenes/billing)
 *   need cutting here. Regressions that reintroduce heavier dependencies are caught by the guard
 *   scripts rather than pre-emptively denied.
 *
 * The enforced invariants live in bin/check-toolbar-size.mjs (eager-chunk budget, per-file
 * CloudFront limit), bin/check-toolbar-graph.mjs (boundary edges, forbidden packages, source
 * budget), and bin/check-toolbar-csp-eval.mjs (no eval on customer pages).
 */
function createToolbarModulePlugin(dirname, extraDeniedPatterns = []) {
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
                    deniedPaths.includes(args.path) ||
                    [...deniedPatterns, ...extraDeniedPatterns].some((pattern) => pattern.test(args.path))
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

// The toolbar ships as two artifacts:
//
//   dist/toolbar.js          — a tiny classic-script loader (src/toolbar/floating/loader.ts). posthog-js
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
        entryPoints: { 'toolbar-app': 'src/toolbar/floating/index.tsx' },
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
        entryPoints: ['src/toolbar/floating/loader.ts'],
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

// The browser extension ships one panel bundle in a folder per browser. Only the manifest differs:
//
//   dist/toolbar-extension/<browser>/manifest.json
//   dist/toolbar-extension/<browser>/panel.html, panel.js, panel.css, background.js, content.js, content.css,
//   assets/, icons/
//
// Load the folder unpacked in Chrome, or as a temporary add-on in Firefox.
const TOOLBAR_EXTENSION_BROWSERS = ['chrome', 'firefox']

const TOOLBAR_EXTENSION_VERSION = '0.1.0'

const TOOLBAR_EXTENSION_BUILD_DIR = 'toolbar-extension-build'

const TOOLBAR_EXTENSION_ICONS = {
    16: 'icons/favicon-16x16.png',
    32: 'icons/favicon-32x32.png',
    128: 'icons/posthog-128x128.png',
    192: 'icons/android-chrome-192x192.png',
}

export function cleanToolbarExtensionBuild(dirname) {
    fs.rmSync(path.resolve(dirname, 'dist', TOOLBAR_EXTENSION_BUILD_DIR), { recursive: true, force: true })
}

/** panel.html isn't an esbuild input, so watch mode rebuilds on its edits only through this. */
function watchExtensionPagesPlugin(dirname) {
    return {
        name: 'watch-toolbar-extension-pages',
        setup(build) {
            build.onLoad({ filter: /extension[\\/]panel\.tsx$/ }, (args) => ({
                contents: fs.readFileSync(args.path, 'utf8'),
                loader: 'tsx',
                watchFiles: [path.resolve(dirname, 'src/toolbar/extension/panel.html')],
            }))
        },
    }
}

function toolbarExtensionBaseConfig(dirname) {
    return {
        outdir: path.resolve(dirname, 'dist', TOOLBAR_EXTENSION_BUILD_DIR),
        // The pages and scripts name their files directly, so they carry no hash.
        entryNames: '[name]',
        // Extension pages resolve assets against their own folder, so URLs stay relative.
        publicPath: undefined,
        loader: { ...commonConfig.loader, '.svg': 'dataurl' },
        define: {
            ...commonConfig.define,
            __POSTHOG_TOOLBAR_PUBLIC_PATH__: JSON.stringify(''),
        },
    }
}

export function getToolbarExtensionBuildConfig(dirname) {
    return {
        ...toolbarExtensionBaseConfig(dirname),
        name: 'Toolbar extension',
        entryPoints: { panel: 'src/toolbar/extension/panel.tsx' },
        format: 'esm',
        // Keeps lazily imported code (such as hedgehog mode, reached through lemon-ui) out of panel.js.
        splitting: true,
        chunkNames: 'chunks/[name]-[hash]',
        extraPlugins: [createToolbarModulePlugin(dirname), watchExtensionPagesPlugin(dirname)],
    }
}

/**
 * The panel injects content.js into the tab with `scripting.executeScript`, which runs a file as a classic script, and
 * Firefox doesn't run a module as a background script. So each of these scripts is one self-contained IIFE.
 */
export function getToolbarExtensionScriptsBuildConfig(dirname) {
    return {
        ...toolbarExtensionBaseConfig(dirname),
        name: 'Toolbar extension scripts',
        entryPoints: {
            background: 'src/toolbar/extension/background.ts',
            content: 'src/toolbar/extension/content.tsx',
            'page-agent': 'src/toolbar/extension/pageAgent.ts',
        },
        format: 'iife',
        splitting: false,
        // An IIFE inlines every lazy import. The content script never runs hedgehog mode (pixi needs `new Function`,
        // which Manifest V3 forbids) or the product tours editor, so they stay out of every page it's injected into.
        extraPlugins: [
            createToolbarModulePlugin(dirname, [
                /^@posthog\/hedgehog-mode$/,
                /product-tours\/editor\/generateStepHtml$/,
            ]),
        ],
    }
}

// Asks for every http and https site, because the panel follows the active tab without a click on the extension
// button, which `activeTab` needs.
function buildToolbarExtensionManifest(browser) {
    const manifest = {
        manifest_version: 3,
        name: 'PostHog',
        description: 'Use the PostHog toolbar in a side panel next to your website.',
        version: TOOLBAR_EXTENSION_VERSION,
        icons: TOOLBAR_EXTENSION_ICONS,
        action: {
            default_title: 'Open PostHog',
            default_icon: TOOLBAR_EXTENSION_ICONS,
        },
        permissions: ['scripting', 'storage'],
        host_permissions: ['http://*/*', 'https://*/*'],
        web_accessible_resources: [{ resources: ['content.css', 'assets/*'], matches: ['http://*/*', 'https://*/*'] }],
    }
    if (browser === 'firefox') {
        manifest.sidebar_action = {
            default_title: 'PostHog',
            default_panel: 'panel.html',
            default_icon: TOOLBAR_EXTENSION_ICONS,
            open_at_install: false,
        }
        // Firefox needs an add-on ID for MV3 storage, and addons.mozilla.org never lets the ID change after the first
        // upload. 140 is the first release that asks the user at install for the data collection declared here.
        manifest.browser_specific_settings = {
            gecko: {
                id: 'toolbar@posthog.com',
                strict_min_version: '140.0',
                // Keep in sync with the "Data collection" section of src/toolbar/extension/README.md.
                data_collection_permissions: {
                    required: ['authenticationInfo', 'browsingActivity', 'websiteContent'],
                    optional: ['technicalAndInteraction'],
                },
            },
        }
        // Firefox runs Manifest V3 background code as an event page, not as a service worker.
        manifest.background = { scripts: ['background.js'] }
    } else {
        manifest.permissions.push('sidePanel')
        manifest.side_panel = { default_path: 'panel.html' }
        // 116 is the first release with `sidePanel.setPanelBehavior`, which opens the panel from the toolbar button.
        manifest.minimum_chrome_version = '116'
        manifest.background = { service_worker: 'background.js' }
    }
    return manifest
}

export function finalizeToolbarExtensionBuild(dirname) {
    const buildDir = path.resolve(dirname, 'dist', TOOLBAR_EXTENSION_BUILD_DIR)
    for (const browser of TOOLBAR_EXTENSION_BROWSERS) {
        const outDir = path.resolve(dirname, 'dist', 'toolbar-extension', browser)
        fs.rmSync(outDir, { recursive: true, force: true })
        fs.cpSync(buildDir, outDir, { recursive: true })
        fs.copyFileSync(path.resolve(dirname, 'src/toolbar/extension/panel.html'), path.resolve(outDir, 'panel.html'))
        for (const icon of Object.values(TOOLBAR_EXTENSION_ICONS)) {
            fs.mkdirSync(path.dirname(path.resolve(outDir, icon)), { recursive: true })
            fs.copyFileSync(path.resolve(dirname, 'public', icon), path.resolve(outDir, icon))
        }
        fs.writeFileSync(
            path.resolve(outDir, 'manifest.json'),
            JSON.stringify(buildToolbarExtensionManifest(browser), null, 4) + '\n'
        )
        fs.writeFileSync(
            path.resolve(
                dirname,
                'dist',
                'toolbar-extension',
                `posthog-toolbar-${browser}-${TOOLBAR_EXTENSION_VERSION}.zip`
            ),
            zipSync(readDirectoryFiles(outDir))
        )
    }
}

function readDirectoryFiles(directory) {
    const files = {}
    for (const entry of fs.readdirSync(directory, { recursive: true, withFileTypes: true })) {
        // Source maps stay in the unpacked folders for local debugging, but would triple the size of the zips.
        if (entry.isFile() && !entry.name.endsWith('.map')) {
            const filePath = path.join(entry.parentPath, entry.name)
            files[path.relative(directory, filePath).split(path.sep).join('/')] = fs.readFileSync(filePath)
        }
    }
    return files
}
