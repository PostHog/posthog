import { Plugin } from 'vite'

/**
 * Custom Vite plugin to handle Node.js polyfills properly
 */
export function polyfillPlugin(): Plugin {
    return {
        name: 'posthog-polyfill',
        config(config) {
            // Ensure we don't externalize polyfills
            config.build = config.build || {}
            config.build.rollupOptions = config.build.rollupOptions || {}

            const originalExternal = config.build.rollupOptions.external
            config.build.rollupOptions.external = (id, parent, isResolved) => {
                // Don't externalize polyfills
                if (id === 'buffer' || id === 'crypto' || id === 'stream' || id === 'util' || id === 'process') {
                    return false
                }

                // Apply original external logic if it exists
                if (typeof originalExternal === 'function') {
                    return originalExternal(id, parent, isResolved)
                } else if (Array.isArray(originalExternal)) {
                    return originalExternal.includes(id)
                } else if (originalExternal) {
                    return originalExternal
                }

                return false
            }
        },
        resolveId(id) {
            // Force resolve polyfills to their browser versions
            if (id === 'buffer') {
                return id
            } // Will be resolved by alias
            if (id === 'crypto') {
                return 'crypto-browserify'
            }
            if (id === 'stream') {
                return 'stream-browserify'
            }
            if (id === 'util') {
                return 'util'
            }
            if (id === 'process') {
                return 'process/browser'
            }
            return null
        },
    }
}
