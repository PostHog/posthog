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
                    // Node.js polyfills for browser
                    buffer: require.resolve('buffer'),
                    crypto: require.resolve('crypto-browserify'),
                },
            },
            define: {
                global: 'globalThis',
                'process.env.NODE_ENV': '"development"',
                // Add Buffer global for browser compatibility
                'process.env': '{}',
                process: JSON.stringify({ env: {}, browser: true }),
            },
            optimizeDeps: {
                include: ['buffer', 'crypto-browserify'],
                // Exclude hogvm from optimization to avoid import issues
                exclude: ['@posthog/hogvm'],
            },
            // Add explicit polyfills for Node.js modules
            build: {
                rollupOptions: {
                    external: ['@storybook/blocks'],
                },
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

    typescript: {
        reactDocgen: 'react-docgen-typescript',
        reactDocgenTypescriptOptions: {
            shouldExtractLiteralValuesFromEnum: true,
            propFilter: (prop) => (prop.parent ? !/node_modules/.test(prop.parent.fileName) : true),
        },
    },
}

export default config
