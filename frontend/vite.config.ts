import mdx from '@mdx-js/rollup'
import react from '@vitejs/plugin-react'
import { URL, fileURLToPath } from 'node:url'
import { resolve } from 'path'
import rehypeMdxCodeProps from 'rehype-mdx-code-props'
import remarkFrontmatter from 'remark-frontmatter'
import { defineConfig } from 'vite'

// import { toolbarDenylistPlugin } from './vite-toolbar-plugin'
import { htmlGenerationPlugin } from './vite-html-plugin'
import { publicAssetsPlugin } from './vite-public-assets-plugin'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isDev = mode === 'development'

    return {
        plugins: [
            react(),
            mdx({
                jsxImportSource: 'react',
                providerImportSource: '@mdx-js/react',
                remarkPlugins: [remarkFrontmatter],
                rehypePlugins: [[rehypeMdxCodeProps, { tagName: 'pre' }]],
            }),
            // We delete and copy the HTML files for development
            htmlGenerationPlugin(),
            // Copy public assets to src/assets for development
            publicAssetsPlugin(),
            // Plugin to handle components/Tab imports in MDX files
            {
                name: 'mdx-components-alias',
                enforce: 'pre',
                resolveId(id, importer) {
                    if (importer?.endsWith('.mdx') && id === 'components/Tab') {
                        return '\0mdx-components-tab'
                    }
                    return null
                },
                load(id) {
                    if (id === '\0mdx-components-tab') {
                        const mdxPath = resolve(__dirname, 'src/scenes/onboarding/MDX.tsx')
                        return `export { Tab as default, Tab } from '${mdxPath}'`
                    }
                    return null
                },
            },
            // Plugin to handle missing imports in MDX files gracefully
            {
                name: 'mdx-ignore-missing-imports',
                enforce: 'pre',
                async resolveId(id, importer) {
                    // If importing from an MDX file, ignore any missing imports
                    // But don't interfere with .mdx imports - let the MDX plugin handle those
                    if (importer?.endsWith('.mdx') && !id.endsWith('.mdx')) {
                        try {
                            const resolved = await this.resolve(id, importer, { skipSelf: true })
                            return resolved
                        } catch {
                            // Any missing import in MDX files - return virtual module
                            return `\0virtual:${id.replace(/[^a-zA-Z0-9]/g, '_')}`
                        }
                    }

                    return null
                },
                load(id) {
                    if (id.startsWith('\0virtual:')) {
                        return 'export default null'
                    }
                    return null
                },
            },
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
                // Docs folder alias for MDX imports
                docs: resolve(__dirname, '../docs'),
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
            // this is just used in dev
            // nosemgrep: trailofbits.javascript.apollo-graphql.v3-cors-audit.v3-potentially-bad-cors
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
