import * as path from 'path'

import { isDev } from '@posthog/esbuilder'

const deniedPaths = [
    '~/lib/hooks/useUploadFiles',
    '~/queries/nodes/InsightViz/InsightViz',
    'lib/hog',
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

const denylistPlugin = {
    /**
     * The toolbar includes many parts of the main posthog app,
     * but we don't want to include everything in the toolbar bundle.
     * Partly because it would be too big, and partly because some things
     * in the main app cause problems for people using CSPs on their sites.
     *
     * It wasn't possible to tree-shake the dependencies out of the bundle,
     * and we don't want to change the app code significantly just for the toolbar
     *
     * So instead we replace some imports in the toolbar with a fake empty module
     *
     * This is ever so slightly hacky, but it gets customers up and running
     *
     * */
    name: 'denylist-imports',
    setup(build) {
        build.onResolve({ filter: /.*/ }, (args) => {
            const shouldDeny =
                deniedPaths.includes(args.path) || deniedPatterns.some((pattern) => pattern.test(args.path))

            if (shouldDeny) {
                return {
                    path: args.path,
                    namespace: 'empty-module',
                    sideEffects: false,
                }
            }
        })

        build.onLoad({ filter: /.*/, namespace: 'empty-module' }, (args) => {
            return {
                contents: `
                                module.exports = new Proxy({}, {
                                    get: function() {
                                        const shouldLog = window?.posthog?.config?.debug
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
        extraPlugins: [denylistPlugin],
    }
}
