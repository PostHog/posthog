import { StorybookConfig } from '@storybook/react-vite'
import { mergeConfig } from 'vite'
import { resolve } from 'path'

const config: StorybookConfig = {
    stories: [
        '../../../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../products/**/frontend/**/*.stories.@(js|jsx|ts|tsx|mdx)',
    ],

    addons: [
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
    ],

    staticDirs: ['public', { from: '../../../frontend/src/assets', to: '/static' }],

    viteFinal: (config) => {
        return mergeConfig(config, {
            resolve: {
                alias: {
                    '~': resolve(__dirname, '../../../frontend/src'),
                    '@': resolve(__dirname, '../../../frontend/src'),
                    lib: resolve(__dirname, '../../../frontend/src/lib'),
                    scenes: resolve(__dirname, '../../../frontend/src/scenes'),
                    queries: resolve(__dirname, '../../../frontend/src/queries'),
                    layout: resolve(__dirname, '../../../frontend/src/layout'),
                    toolbar: resolve(__dirname, '../../../frontend/src/toolbar'),
                    taxonomy: resolve(__dirname, '../../../frontend/src/taxonomy'),
                    models: resolve(__dirname, '../../../frontend/src/models'),
                    mocks: resolve(__dirname, '../../../frontend/src/mocks'),
                    exporter: resolve(__dirname, '../../../frontend/src/exporter'),
                    stories: resolve(__dirname, '../../../frontend/src/stories'),
                    types: resolve(__dirname, '../../../frontend/src/types.ts'),
                    '@posthog/lemon-ui': resolve(__dirname, '../../../frontend/@posthog/lemon-ui/src/index'),
                    '@posthog/lemon-ui/': resolve(__dirname, '../../../frontend/@posthog/lemon-ui/src/'),
                    storybook: resolve(__dirname, '../../../frontend/.storybook'),
                    '@posthog/ee/exports': resolve(__dirname, '../../../ee/frontend/exports.ts'),
                    public: resolve(__dirname, '../../../frontend/src/assets'),
                    products: resolve(__dirname, '../../../products'),
                    cypress: resolve(__dirname, '../../../cypress'),
                },
            },
            define: {
                global: 'globalThis',
                'process.env.NODE_ENV': '"development"',
                // Add process.env polyfill
                'process.env': '{}',
            },
            optimizeDeps: {
                include: ['buffer', 'crypto-browserify', '@posthog/hogvm'],
            },
            build: {
                rollupOptions: {
                    external: ['@storybook/blocks'],
                },
            },
            // Prevent externalization of Node.js modules in browser builds
            ssr: {
                noExternal: ['buffer', '@posthog/hogvm', 'crypto-browserify'],
            },
        })
    },

    framework: {
        name: '@storybook/react-vite',
        options: {},
    },

    docs: {
        autodocs: 'tag',
    },
}

export default config
