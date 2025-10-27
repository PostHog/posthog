import react from '@vitejs/plugin-react'
import { URL, fileURLToPath } from 'node:url'
import { resolve } from 'path'
import { defineConfig } from 'vite'

import { assetCopyPlugin } from './vite-asset-plugin'
// import { toolbarDenylistPlugin } from './vite-toolbar-plugin'
import { htmlGenerationPlugin } from './vite-html-plugin'
import { polyfillPlugin } from './vite-polyfill-plugin'
import { publicAssetsPlugin } from './vite-public-assets-plugin'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isDev = mode === 'development'

    return {
        plugins: [
            react(),
            // Handle Node.js polyfills properly
            polyfillPlugin(),
            // We delete and copy the HTML files for development
            htmlGenerationPlugin(),
            // Copy public assets to src/assets for development
            publicAssetsPlugin(),
            // Copy assets (WASM, RRWeb workers, public files) for production builds
            assetCopyPlugin(),
            {
                name: 'startup-message',
                configureServer(server) {
                    server.httpServer?.once('listening', () => {
                        setTimeout(() => {
                            console.info(`
――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

   🚀 Visit http://localhost:8010 to see the app
   ⚠️  You may need to wait for the other services to start

――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――
`)
                        }, 1000)
                    })
                },
            },
        ],
        resolve: {
            alias: {
                '~': fileURLToPath(new URL('./src', import.meta.url)),
                '@': fileURLToPath(new URL('./src', import.meta.url)),
                // Add direct mappings for PostHog's import structure from tsconfig.json
                lib: resolve(__dirname, 'src/lib'),
                scenes: resolve(__dirname, 'src/scenes'),
                queries: resolve(__dirname, 'src/queries'),
                layout: resolve(__dirname, 'src/layout'),
                toolbar: resolve(__dirname, 'src/toolbar'),
                taxonomy: resolve(__dirname, 'src/taxonomy'),
                models: resolve(__dirname, 'src/models'),
                mocks: resolve(__dirname, 'src/mocks'),
                exporter: resolve(__dirname, 'src/exporter'),
                stories: resolve(__dirname, 'src/stories'),
                types: resolve(__dirname, 'src/types.ts'),
                // @posthog/lemon-ui aliases
                '@posthog/lemon-ui': resolve(__dirname, '@posthog/lemon-ui/src/index'),
                '@posthog/lemon-ui/': resolve(__dirname, '@posthog/lemon-ui/src/'),
                // Other aliases from tsconfig.json
                storybook: resolve(__dirname, '../.storybook'),
                '@posthog/ee/exports': resolve(__dirname, '../ee/frontend/exports.ts'),
                // Just for Vite: we copy public assets to src/assets, we need to alias it to the correct path
                public: resolve(__dirname, 'src/assets'),
                products: resolve(__dirname, '../products'),
                // Node.js polyfills for browser compatibility
                buffer: 'buffer',
                crypto: 'crypto-browserify',
                stream: 'stream-browserify',
                util: 'util',
                process: 'process/browser',
            },
        },
        build: {
            // Generate manifest for backend integration
            manifest: true,
            outDir: 'dist',
            rollupOptions: {
                input: {
                    // Main PostHog App - matches ESBuild entryPoints
                    index: resolve(__dirname, 'src/index.tsx'),
                    // Exporter - matches ESBuild entryPoints
                    exporter: resolve(__dirname, 'src/exporter/index.tsx'),
                    // Render Query - matches ESBuild entryPoints
                    'render-query': resolve(__dirname, 'src/render-query/index.tsx'),
                    // Toolbar - matches ESBuild entryPoints
                    toolbar: resolve(__dirname, 'src/toolbar/index.tsx'),
                    // Test Worker - matches ESBuild testWorker entry
                    testWorker: resolve(__dirname, 'src/scenes/session-recordings/player/testWorker.ts'),
                },
                output: {
                    // Match ESBuild naming: no hashes in dev, hashes in prod
                    entryFileNames: isDev ? '[name].js' : '[name]-[hash].js',
                    chunkFileNames: isDev ? 'chunk-[name].js' : 'chunk-[name]-[hash].js',
                    assetFileNames: isDev ? 'assets/[name].[ext]' : 'assets/[name]-[hash].[ext]',
                    // Configure specific formats for different entries to match ESBuild
                    manualChunks: undefined, // Let Vite handle chunking automatically
                },
                external: (id) => {
                    // Don't externalize polyfills - let them be bundled
                    if (['buffer', 'crypto', 'stream', 'util', 'process'].some((polyfill) => id.includes(polyfill))) {
                        return false
                    }
                    // Externalize other Node.js built-ins
                    return ['fs', 'path', 'os'].includes(id)
                },
            },
            sourcemap: true,
            // Ensure proper handling of large bundles
            chunkSizeWarningLimit: 2000,
        },
        worker: {
            format: 'es', // Use ES modules to support WASM imports
            plugins: () => [react()],
            rollupOptions: {
                output: {
                    // Match ESBuild worker naming
                    entryFileNames: isDev ? '[name].js' : '[name]-[hash].js',
                    chunkFileNames: isDev ? 'worker-chunk-[name].js' : 'worker-chunk-[name]-[hash].js',
                },
            },
        },
        server: {
            port: 8234,
            host: process.argv.includes('--host') ? '0.0.0.0' : 'localhost',
            cors: {
                // Allow Django backend to access Vite dev server
                origin: ['http://localhost:8000', 'http://localhost:8010'],
            },
            // Configure origin for proper asset URL generation
            origin: 'http://localhost:8234',
        },
        define: {
            global: 'globalThis',
            'process.env.NODE_ENV': isDev ? '"development"' : '"production"',
            // Match ESBuild defines exactly
            __DEV__: isDev,
            __PROD__: !isDev,
        },
        css: {
            devSourcemap: true,
        },
        optimizeDeps: {
            include: [
                'react',
                'react-dom',
                'buffer',
                'crypto-browserify',
                'stream-browserify',
                'util',
                'process/browser',
            ],
            exclude: ['snappy-wasm'], // Don't pre-bundle snappy-wasm so WASM file stays with JS
        },
        // Add Node.js polyfills
        esbuild: {
            // Define global to match ESBuild behavior
            define: {
                global: 'globalThis',
            },
        },
        ssr: {
            noExternal: ['buffer', 'crypto-browserify', 'stream-browserify', 'util', 'process'],
        },
    }
})
