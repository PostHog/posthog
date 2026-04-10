import react from '@vitejs/plugin-react'
import { URL, fileURLToPath } from 'node:url'
import { resolve } from 'path'
import { defineConfig } from 'vite'

// import { toolbarDenylistPlugin } from './vite-toolbar-plugin'
import { htmlGenerationPlugin } from './plugins/vite-html-plugin'
import { posthogJsPlugin } from './plugins/vite-posthog-js-plugin'
import { publicAssetsPlugin } from './plugins/vite-public-assets-plugin'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isDev = mode === 'development'

    return {
        plugins: [
            react(),
            // We delete and copy the HTML files for development
            htmlGenerationPlugin(),
            // Copy public assets to src/assets for development
            publicAssetsPlugin(),
            // Copy posthog-js files from node_modules to dist for development
            posthogJsPlugin(),
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
                // Just for Vite: we copy public assets to src/assets, we need to alias it to the correct path
                public: resolve(__dirname, 'src/assets'),
                products: resolve(__dirname, '../products'),
                '@posthog/shared-onboarding': resolve(__dirname, '../docs/onboarding'),
                '@posthog/shared-onboarding/*': resolve(__dirname, '../docs/onboarding/*'),
                // Node.js polyfills for browser compatibility
                buffer: 'buffer',
            },
        },
        build: {
            // Generate manifest for backend integration
            manifest: true,
            outDir: 'dist',
            rollupOptions: {
                input: {
                    index: resolve(__dirname, 'src/index.tsx'),
                    exporter: resolve(__dirname, 'src/exporter/index.tsx'),
                    render_query: resolve(__dirname, 'src/render-query/index.tsx'),
                    toolbar: resolve(__dirname, 'src/toolbar/index.tsx'),
                },
                output: {
                    entryFileNames: isDev ? '[name].js' : '[name]-[hash].js',
                    chunkFileNames: isDev ? 'chunk-[name].js' : 'chunk-[name]-[hash].js',
                    assetFileNames: isDev ? '~/assets/[name].[ext]' : '~/assets/[name]-[hash].[ext]',
                },
            },
            sourcemap: true,
        },
        worker: {
            format: 'es', // Use ES modules to support WASM imports
            plugins: () => [react()],
            rollupOptions: {
                output: {
                    entryFileNames: isDev ? '[name].js' : '[name]-[hash].js',
                },
            },
        },
        server: {
            port: 8234,
            host: process.argv.includes('--host') || process.env.POSTHOG_SANDBOX ? '0.0.0.0' : 'localhost',
            // nosemgrep: trailofbits.javascript.apollo-graphql.v3-cors-audit.v3-potentially-bad-cors
            cors: true,
            allowedHosts: true,
            // JS_URL overrides for sandbox environments where Vite is exposed
            // through a reverse proxy at a different origin (same-origin via
            // Caddy in local sandboxes, https FQDN via Tailscale in cloud).
            origin: process.env.JS_URL || 'http://localhost:8234',
            hmr: (() => {
                if (!process.env.JS_URL) {
                    return undefined
                }
                const parsed = new URL(process.env.JS_URL)
                const isHttps = parsed.protocol === 'https:'
                return {
                    host: parsed.hostname,
                    // No explicit port means 443 for https, 80 for http.
                    clientPort: parsed.port ? parseInt(parsed.port) : isHttps ? 443 : 80,
                    protocol: isHttps ? 'wss' : 'ws',
                    // Dedicated path so the sandbox Caddy @vite matcher can
                    // route the HMR websocket to Vite instead of Django.
                    path: '/vite-hmr',
                }
            })(),
            proxy: {
                '/static': {
                    target: 'http://localhost:8000',
                    changeOrigin: true,
                },
            },
        },
        define: {
            global: 'globalThis',
            'process.env.NODE_ENV': isDev ? '"development"' : '"production"',
        },
        css: {
            devSourcemap: true,
        },
        optimizeDeps: {
            include: ['react', 'react-dom', 'buffer'],
            exclude: ['snappy-wasm'], // Don't pre-bundle snappy-wasm so WASM file stays with JS
        },
    }
})
