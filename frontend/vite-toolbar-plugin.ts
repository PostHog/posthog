import type { Plugin } from 'vite'

// Explicit denylist of paths we don't want in the toolbar bundle
const deniedPaths = [
    '~/lib/hooks/useUploadFiles',
    '~/queries/nodes/InsightViz/InsightViz',
    'lib/hog',
    'scenes/activity/explore/EventDetails',
    'scenes/web-analytics/WebAnalyticsDashboard',
]

// Patterns to match for denying imports
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

export function toolbarDenylistPlugin(): Plugin {
    return {
        name: 'toolbar-denylist',
        resolveId(source, importer) {
            // Only apply to toolbar bundle
            if (!importer?.includes('toolbar')) {
                return null
            }

            const shouldDeny =
                deniedPaths.includes(source) ||
                deniedPatterns.some((pattern) => pattern.test(source))

            if (shouldDeny) {
                // Return a virtual module ID
                return `\0denied:${source}`
            }

            return null
        },
        load(id) {
            // Handle virtual modules for denied imports
            if (id.startsWith('\0denied:')) {
                const originalPath = id.replace('\0denied:', '')
                return `
                    // Denied import: ${originalPath}
                    // This module is intentionally empty to reduce toolbar bundle size
                    // and avoid CSP issues on customer sites
                    
                    const deniedModule = new Proxy({}, {
                        get: function(target, prop) {
                            const shouldLog = window?.posthog?.config?.debug
                            if (shouldLog) {
                                console.warn('[TOOLBAR] Attempted to use denied module:', '${originalPath}', 'property:', prop);
                            }
                            return function() { 
                                return {} 
                            }
                        }
                    });
                    
                    export default deniedModule;
                    export * from deniedModule;
                `
            }

            return null
        },
    }
} 