import * as path from 'path'

import { isDev } from '@posthog/esbuilder'

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
        globalName: 'posthogToolbar',
        entryPoints: ['src/toolbar/index.tsx'],
        format: 'iife',
        outfile: path.resolve(dirname, 'dist', 'toolbar.js'),
        banner: { js: 'var posthogToolbar = (function () { var define = undefined;' },
        footer: { js: 'return posthogToolbar })();' },
        publicPath: isDev ? '/static/' : 'https://us.posthog.com/static/',
        writeMetaFile: true,
        extraPlugins: [createToolbarModulePlugin(dirname)],
    }
}
