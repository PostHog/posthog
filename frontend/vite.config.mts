import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve } from 'node:path'
import { URL, fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const __dirname = dirname(fileURLToPath(import.meta.url))

// import { toolbarDenylistPlugin } from './vite-toolbar-plugin'
import { htmlGenerationPlugin } from './plugins/vite-html-plugin'
import { posthogJsPlugin } from './plugins/vite-posthog-js-plugin'
import { publicAssetsPlugin } from './plugins/vite-public-assets-plugin'

// In dev we let `@tailwindcss/vite` compile Tailwind on-demand instead of
// running the standalone CLI watcher and re-importing its output. Mapping the
// precompiled path to the source CSS keeps `global.scss` (which is shared with
// the production esbuild build) untouched while letting Vite process the
// `@import 'tailwindcss';` / `@config` directives directly.
const tailwindSource = resolve(__dirname, '../common/tailwind/tailwind.css')
const tailwindDevSourcePlugin = {
    name: 'posthog-tailwind-dev-source',
    enforce: 'pre' as const,
    resolveId(source: string) {
        const normalized = source.replaceAll('\\', '/')
        if (
            normalized.endsWith('@posthog/tailwind/dist/tailwind.css') ||
            normalized.endsWith('/common/tailwind/dist/tailwind.css')
        ) {
            return tailwindSource
        }
        return null
    },
}

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isDev = mode === 'development'

    return {
        plugins: [
            // Only run Tailwind via Vite in dev. Production goes through the
            // standalone CLI in `common/tailwind` and the precompiled CSS, so
            // we must not redirect that import or double-compile here.
            ...(isDev ? [tailwindDevSourcePlugin, tailwindcss()] : []),
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
            host: process.argv.includes('--host') ? '0.0.0.0' : 'localhost',
            allowedHosts: process.env.VITE_ALLOWED_HOSTS?.split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            // nosemgrep: trailofbits.javascript.apollo-graphql.v3-cors-audit.v3-potentially-bad-cors
            cors: true,
            // JS_URL overrides for sandbox environments where Vite is exposed on a different port.
            origin: process.env.JS_URL || 'http://localhost:8234',
            hmr: process.env.JS_URL ? { clientPort: parseInt(process.env.JS_URL.split(':').pop()!) } : undefined,
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
