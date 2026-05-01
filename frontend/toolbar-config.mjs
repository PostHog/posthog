import * as path from 'path'

import { commonConfig, isDev } from '@posthog/esbuilder'

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
    return {
        name: 'toolbar-module-replacements',
        setup(build) {
            build.onResolve({ filter: /.*/ }, (args) => {
                const shimFile = shimmedModules[args.path]
                if (shimFile) {
                    return { path: path.resolve(dirname, shimFile) }
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

export function getToolbarBuildConfig(dirname) {
    return {
        name: 'Toolbar',
        globalName: '__posthogToolbarModule',
        entryPoints: ['src/toolbar/index.tsx'],
        format: 'iife',
        outfile: path.resolve(dirname, 'dist', 'toolbar.js'),
        banner: { js: 'var __posthogToolbarModule = (function () { var define = undefined;' },
        footer: { js: 'return __posthogToolbarModule })();' },
        publicPath: isDev ? '/static/' : toolbarPublicPathOverride || 'https://us.posthog.com/static/',
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
