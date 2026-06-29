import type { StorybookConfig } from '@storybook/react-vite'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import * as path from 'path'
import { mergeConfig } from 'vite'

import { frontendResolvePlugin } from './plugins/vite-frontend-resolve-plugin'
import { moduleGraphPlugin } from './plugins/vite-module-graph-plugin'
import { sqlRawPlugin } from './plugins/vite-sql-raw-plugin'

// Storybook 10 loads the config as a native ES module, where `__dirname` is
// not defined — derive it from the module URL instead.
const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Repo root = three levels up from this file (common/storybook/.storybook/main.ts).
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')
const FRONTEND = path.resolve(REPO_ROOT, 'frontend')

const createStoriesPathFor = (storyPath: string): string => `../../../${storyPath}/**/*.stories.@(js|jsx|ts|tsx)`

const config: StorybookConfig = {
    stories: [
        createStoriesPathFor('frontend/src'),
        createStoriesPathFor('products/**/frontend'),
        createStoriesPathFor('products/**/mcp/apps'),
        createStoriesPathFor('services/mcp/src/ui-apps'),
        createStoriesPathFor('packages/quill/packages/charts/src'),
    ],

    addons: ['@storybook/addon-docs', '@storybook/addon-links', '@storybook/addon-a11y'],

    staticDirs: [
        'public',
        { from: '../../../frontend/public', to: '/static' },
        { from: '../../../frontend/node_modules/@posthog/hedgehog-mode/assets', to: '/static/hedgehog-mode' },
    ],

    framework: {
        name: '@storybook/react-vite',
        options: {},
    },

    viteFinal: (viteConfig) =>
        mergeConfig(viteConfig, {
            plugins: [frontendResolvePlugin(REPO_ROOT), tailwindcss(), sqlRawPlugin(), moduleGraphPlugin(REPO_ROOT)],
            resolve: {
                // Keep a single copy of these in the monorepo.
                // Duplicate react/kea instances break hooks and kea's context.
                ...((): Pick<NonNullable<Parameters<typeof mergeConfig>[1]['resolve']>, 'dedupe' | 'alias'> => {
                    const SINGLETON_PACKAGES = [
                        'react',
                        'react-dom',
                        '@base-ui/react',
                        'kea',
                        'kea-router',
                        'kea-forms',
                        'kea-loaders',
                        'kea-localstorage',
                        'kea-subscriptions',
                        'kea-waitfor',
                        'kea-window-values',
                    ]
                    return {
                        dedupe: SINGLETON_PACKAGES,
                        alias: Object.fromEntries(
                            SINGLETON_PACKAGES.map((pkg) => [pkg, path.resolve(FRONTEND, 'node_modules', pkg)])
                        ),
                    }
                })(),
                alias: {
                    // The app's runtime deps live in frontend/node_modules, not under
                    // common/storybook. Webpack reached them via resolve.modules; Vite has no
                    // equivalent, so point the ones imported by bundled app/quill code there.
                    ...Object.fromEntries(
                        [
                            'react',
                            'react-dom',
                            '@base-ui/react',
                            'kea',
                            'kea-router',
                            'kea-forms',
                            'kea-loaders',
                            'kea-localstorage',
                            'kea-subscriptions',
                            'kea-waitfor',
                            'kea-window-values',
                        ].map((pkg) => [pkg, path.resolve(FRONTEND, 'node_modules', pkg)])
                    ),
                    '~': path.resolve(FRONTEND, 'src'),
                    lib: path.resolve(FRONTEND, 'src', 'lib'),
                    scenes: path.resolve(FRONTEND, 'src', 'scenes'),
                    queries: path.resolve(FRONTEND, 'src', 'queries'),
                    layout: path.resolve(FRONTEND, 'src', 'layout'),
                    taxonomy: path.resolve(FRONTEND, 'src', 'taxonomy'),
                    models: path.resolve(FRONTEND, 'src', 'models'),
                    mocks: path.resolve(FRONTEND, 'src', 'mocks'),
                    exporter: path.resolve(FRONTEND, 'src', 'exporter'),
                    types: path.resolve(FRONTEND, 'src', 'types.ts'),
                    public: path.resolve(FRONTEND, 'public'),
                    products: path.resolve(REPO_ROOT, 'products'),
                    '@common': path.resolve(REPO_ROOT, 'common'),
                    '@posthog/lemon-ui': path.resolve(FRONTEND, '@posthog', 'lemon-ui', 'src'),
                    '@posthog/mcp-ui': path.resolve(REPO_ROOT, 'services', 'mcp', 'src', 'ui-apps', 'lib'),
                    '@posthog/shared-onboarding': path.resolve(REPO_ROOT, 'docs', 'onboarding'),
                    '@posthog/quill': path.resolve(REPO_ROOT, 'packages', 'quill', 'packages', 'quill', 'src'),
                    '@posthog/quill-charts': path.resolve(REPO_ROOT, 'packages', 'quill', 'packages', 'charts', 'src'),
                },
            },
            define: {
                global: 'globalThis',
            },
            optimizeDeps: {
                include: ['buffer'],
            },
        }),

    docs: {
        autodocs: 'tag',
    },
}

export default config
