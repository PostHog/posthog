import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve } from 'node:path'
import { URL, fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const __dirname = dirname(fileURLToPath(import.meta.url))

// import { toolbarDenylistPlugin } from './vite-toolbar-plugin'
import { loadPrebundledDeps } from './plugins/vite-deps-cache'
import { htmlGenerationPlugin } from './plugins/vite-html-plugin'
import { posthogJsPlugin } from './plugins/vite-posthog-js-plugin'
import { publicAssetsPlugin } from './plugins/vite-public-assets-plugin'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isDev = mode === 'development'

    // On a cold start Vite scans the whole first-party module graph (~3s) just to discover the
    // node_modules it must pre-bundle. When a committed snapshot of that set still matches the
    // current dependency closure, feed it directly and skip the scan. Only in dev serve — the
    // production build does its own bundling.
    const prebundledDeps = isDev && !process.env.VITE_DEPS_REGEN ? loadPrebundledDeps(__dirname) : null

    if (isDev && !process.env.VITE_DEPS_REGEN) {
        if (prebundledDeps) {
            console.info(`⚡ Reusing pre-bundle snapshot (${prebundledDeps.include.length} deps) — skipping cold scan`)
        } else {
            console.info(
                'ℹ️  No matching vite.deps.json snapshot — running full scan. Run `pnpm vite:deps` to speed up cold starts.'
            )
        }
    }

    // Resolve aliases so the optimizer can pre-bundle `products/*`-scoped deps that don't resolve
    // from the frontend root. Paths in the snapshot are stored relative to this dir.
    const prebundledAliases = Object.fromEntries(
        Object.entries(prebundledDeps?.aliases ?? {}).map(([name, rel]) => [name, resolve(__dirname, rel)])
    )

    // The optimizer re-resolves every include specifier through the resolver chain on each cold
    // start (~1s for 230 specifiers, sequentially). Its resolver honors resolve.alias, so replay
    // the snapshot's recorded resolutions through a single exact-match alias entry: one anchored
    // alternation regex (so subpaths like `pkg/sub` are untouched unless they're snapshot entries
    // themselves) plus an O(1) map lookup. Applies only while the fingerprint-gated snapshot is
    // active; the recorded file is what resolution produced at generation time, so runtime
    // imports resolve identically.
    const prebundledResolved = prebundledDeps?.resolved ?? {}
    const escapeRegExp = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const prebundledResolveEntries =
        Object.keys(prebundledResolved).length > 0
            ? [
                  {
                      find: new RegExp(`^(?:${Object.keys(prebundledResolved).map(escapeRegExp).join('|')})$`),
                      replacement: '$&',
                      customResolver: (id: string): string | null =>
                          prebundledResolved[id] ? resolve(__dirname, prebundledResolved[id]) : null,
                  },
              ]
            : []

    return {
        plugins: [
            react(),
            tailwindcss(),
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
                        // Tiny delay only so this prints below Vite's own ready banner.
                        setTimeout(() => {
                            console.info(`
――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

   🚀 Visit http://localhost:8010 to see the app
   ⚠️  You may need to wait for the other services to start

――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――
`)
                        }, 100)
                    })
                },
            },
        ],
        resolve: {
            dedupe: ['@base-ui/react'],
            alias: [
                // Exact-match replay of the snapshot's recorded dep resolutions (dev only, empty
                // without an active snapshot) — must come first so it wins for bare specifiers.
                ...prebundledResolveEntries,
                ...Object.entries({
                    // products/*-scoped deps, so the cold-start optimizer can pre-bundle them (dev only).
                    ...prebundledAliases,
                    '@base-ui/react': resolve(__dirname, 'node_modules/@base-ui/react'),
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
                    types: resolve(__dirname, 'src/types.ts'),
                    // @posthog/lemon-ui aliases
                    '@posthog/lemon-ui': resolve(__dirname, '@posthog/lemon-ui/src/index'),
                    '@posthog/lemon-ui/': resolve(__dirname, '@posthog/lemon-ui/src/'),
                    // Other aliases from tsconfig.json
                    storybook: resolve(__dirname, '../.storybook'),
                    // Just for Vite: we copy public assets to src/assets, we need to alias it to the correct path
                    public: resolve(__dirname, 'src/assets'),
                    // Required for production builds — @posthog/icons is in the pnpm store, not node_modules root
                    '@posthog/icons': resolve(__dirname, 'node_modules/@posthog/icons'),
                    products: resolve(__dirname, '../products'),
                    '@posthog/shared-onboarding': resolve(__dirname, '../docs/onboarding'),
                    '@posthog/shared-onboarding/*': resolve(__dirname, '../docs/onboarding/*'),
                    // Node.js polyfills for browser compatibility
                    buffer: 'buffer',
                }).map(([find, replacement]) => ({ find, replacement })),
            ],
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
            // The rest of the stack hardcodes 8234, so falling back to another port serves a
            // broken app (the browser keeps talking to whatever squats 8234). Fail loudly instead;
            // bin/start-frontend reclaims the port from stale processes before launching.
            strictPort: true,
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
            include: prebundledDeps?.include ?? ['react', 'react-dom', 'buffer'],
            // With a fingerprint-matched snapshot the include list is complete, so disable the
            // cold-start scan. Without it, keep discovery on so nothing is missed.
            //
            // Tradeoff: while noDiscovery is on, first-importing an already-installed dep that
            // isn't in the snapshot won't auto-optimize (no lockfile change means the fingerprint
            // still matches). Re-run `pnpm vite:deps` and restart to refresh it. Installing a dep
            // changes the lockfile, which flips the fingerprint and falls back to discovery anyway.
            noDiscovery: prebundledDeps != null,
            rolldownOptions: {
                plugins: [
                    {
                        // Vite hardcodes sourcemap: 'hidden' for pre-bundled deps, which is most
                        // of the optimize time and ~90MB of writes per cold start. Deps are
                        // node_modules code; skip their sourcemaps in dev. This hook runs after
                        // Vite's own output options, so it can win.
                        name: 'posthog:no-dep-sourcemaps',
                        outputOptions(options: { sourcemap?: boolean | 'inline' | 'hidden' }) {
                            options.sourcemap = false
                            return options
                        },
                    },
                ],
            },
            // snappy-wasm: don't pre-bundle so the WASM file stays with the JS.
            // @posthog/brand: its PNG stubs resolve assets via `new URL(..., import.meta.url)`,
            // which pre-bundling rewrites to .vite/deps/ where the images don't exist — hoggie
            // art silently 404s in dev serve (production builds are unaffected).
            exclude: ['snappy-wasm', '@posthog/brand'],
        },
    }
})
