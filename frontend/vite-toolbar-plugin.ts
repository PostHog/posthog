import { Plugin } from 'vite'

/**
 * Vite plugin to replicate ESBuild's toolbar deny-list functionality
 * This plugin replaces specific imports in the toolbar with empty modules
 * to reduce bundle size and avoid CSP issues
 */
export function toolbarDenylistPlugin(): Plugin {
    return {
        name: 'posthog-toolbar-denylist',
        resolveId(id, importer) {
            // Only apply to toolbar builds
            if (!importer?.includes('toolbar/index.tsx') && !importer?.includes('src/toolbar/')) {
                return null
            }

            // Explicit denylist of paths we don't want in the toolbar bundle
            const deniedPaths = [
                '~/lib/hooks/useUploadFiles',
                '~/queries/nodes/InsightViz/InsightViz',
                'lib/hog',
                'scenes/activity/explore/EventDetails',
                'scenes/web-analytics/WebAnalyticsDashboard',
                'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager.ts',
            ]

            // Patterns to match for denying imports
            const deniedPatterns = [
                /monaco/,
                /scenes\/insights\/filters\/ActionFilter/,
                /lib\/components\/CodeSnippet/,
                /scenes\/session-recordings\/player/,
                /queries\/schema-guard/,
                /queries\/schema\.json/,
                /queries\/QueryEditor\/QueryEditor/,
                /scenes\/billing/,
                /scenes\/data-warehouse/,
                /LineGraph/,
            ]

            const shouldDeny = deniedPaths.includes(id) || deniedPatterns.some((pattern) => pattern.test(id))

            if (shouldDeny) {
                return `virtual:toolbar-denied:${id}`
            }

            return null
        },
        load(id) {
            if (id.startsWith('virtual:toolbar-denied:')) {
                const originalPath = id.replace('virtual:toolbar-denied:', '')

                return `
// Empty module - denied for toolbar bundle
// Original path: ${originalPath}
export default new Proxy({}, {
    get: function(target, prop) {
        const shouldLog = window?.posthog?.config?.debug
        if (shouldLog) {
            console.warn('[TOOLBAR] Attempted to use denied module:', ${JSON.stringify(originalPath)});
        }
        return function() {
            return {}
        }
    }
});

// Export common patterns that might be imported
export const Component = () => null;
export const hook = () => ({});
export const util = () => ({});
export const config = {};
`
            }
            return null
        },
    }
}
