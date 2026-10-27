import type { StorybookConfig } from '@storybook/react-vite'
import tailwindcss from '@tailwindcss/vite'
import { redact } from '@tanstack/redact/vite'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import * as path from 'path'
import { type Alias, type InlineConfig, mergeConfig, type Rollup } from 'vite'

import { zodJitlessPlugin } from '../../../frontend/plugins/vite-zod-jitless-plugin.ts'
import { frontendResolvePlugin } from './plugins/vite-frontend-resolve-plugin.ts'
import { moduleGraphPlugin } from './plugins/vite-module-graph-plugin.ts'
import { sqlRawPlugin } from './plugins/vite-sql-raw-plugin.ts'

// Storybook 10 loads the config as a native ES module, where `__dirname` is
// not defined — derive it from the module URL instead.
const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Repo root = three levels up from this file (common/storybook/.storybook/main.ts).
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')
const FRONTEND = path.resolve(REPO_ROOT, 'frontend')

// Keep a single copy of these in the monorepo — duplicate react/kea instances
// break hooks and kea's context. Aliased to the app's copy and deduped.
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
    '@testing-library/dom',
]

const isRedactEnabled = process.env.POSTHOG_REACT_RUNTIME === 'redact'

// Vite applies `resolve.alias` before any plugin, so exact-match aliases must point React at Redact.
const REDACT_ALIASES: Record<string, string> = {
    react: '@tanstack/redact',
    'react/jsx-runtime': '@tanstack/redact/jsx-runtime',
    'react/jsx-dev-runtime': '@tanstack/redact/jsx-dev-runtime',
    'react-dom': '@tanstack/redact/dom',
    'react-dom/client': '@tanstack/redact/dom-client',
    'react-dom/server': '@tanstack/redact/server',
    'react-dom/test-utils': '@tanstack/redact/dom-test-utils',
    scheduler: '@tanstack/redact/scheduler',
    'use-sync-external-store': '@tanstack/redact',
    'use-sync-external-store/shim': '@tanstack/redact',
    'use-sync-external-store/shim/index.js': '@tanstack/redact',
    'use-sync-external-store/shim/with-selector': '@tanstack/redact',
    'use-sync-external-store/shim/with-selector.js': '@tanstack/redact',
}

function withReactRuntimeAliases(aliases: Record<string, string>): Record<string, string> | Alias[] {
    if (!isRedactEnabled) {
        return aliases
    }
    const entries = Object.entries(aliases).map(([find, replacement]) => ({ find, replacement }))
    const require = createRequire(import.meta.url)
    return [
        ...Object.entries(REDACT_ALIASES).map(([specifier, target]) => ({
            find: new RegExp(`^${specifier.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')}$`),
            replacement: require.resolve(target),
        })),
        ...entries.filter(({ find }) => !(find in REDACT_ALIASES)),
    ]
}

// addon-docs adds a plugin that aliases react and react-dom to the installed React.
function withoutStorybookReactAliases(viteConfig: InlineConfig): InlineConfig {
    if (!isRedactEnabled) {
        return viteConfig
    }
    return {
        ...viteConfig,
        plugins: viteConfig.plugins?.filter(
            (plugin) => !(plugin && 'name' in plugin && plugin.name === 'storybook:package-deduplication')
        ),
    }
}

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
        // Web workers the app loads by fixed URL from /static (Monaco, HogQL parser). Django
        // serves them from frontend/dist; here `pnpm build:workers` builds them into .workers.
        // Without them, every `new Worker(...)` 404s, and the resulting error event fails any
        // story whose play function is still running when it fires.
        { from: '../.workers', to: '/static' },
        { from: '../../../frontend/node_modules/@posthog/hedgehog-mode/assets', to: '/static/hedgehog-mode' },
        // EmojiPickerPanel loads frimousse's emoji data from here. The app build copies the same files into dist.
        { from: '../../../frontend/node_modules/emojibase-data/en', to: '/static/emoji/en' },
        // The replay player mounts rrweb into this document rather than the app's, so a recorded
        // page is judged against its policy instead of ours. Django renders the same file; serving
        // it here keeps stories on the real path rather than a Storybook-only stand-in.
        { from: '../../../posthog/templates/replay_player_frame', to: '/replay_player_frame' },
    ],

    framework: {
        name: '@storybook/react-vite',
        options: {},
    },

    viteFinal: (viteConfig) =>
        mergeConfig(withoutStorybookReactAliases(viteConfig), {
            plugins: [
                frontendResolvePlugin(REPO_ROOT),
                tailwindcss(),
                sqlRawPlugin(),
                moduleGraphPlugin(REPO_ROOT),
                zodJitlessPlugin(),
                ...(isRedactEnabled ? [redact({ resolveFrom: FRONTEND })] : []),
            ],
            resolve: {
                dedupe: SINGLETON_PACKAGES,
                alias: withReactRuntimeAliases({
                    // react-shadow (the toolbar's shadow-DOM renderer) imports react-dom/server.
                    // The `react-dom` singleton alias below is a prefix match, so it would rewrite
                    // this subpath to a bare path and resolve the `default` (node) export —
                    // server.node.js extends stream.Readable, which is undefined in the browser
                    // build and throws at module eval. Pin the browser build, ahead of that alias.
                    'react-dom/server': path.resolve(FRONTEND, 'node_modules', 'react-dom', 'server.browser.js'),
                    // The app's runtime deps live in frontend/node_modules, not under
                    // common/storybook. Webpack reached them via resolve.modules; Vite has no
                    // equivalent, so point the ones imported by bundled app/quill code there.
                    ...Object.fromEntries(
                        SINGLETON_PACKAGES.map((pkg) => [pkg, path.resolve(FRONTEND, 'node_modules', pkg)])
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
                    '@posthog/agent-contracts': path.resolve(
                        REPO_ROOT,
                        'packages',
                        'agent',
                        'packages',
                        'agent-contracts',
                        'src'
                    ),
                }),
            },
            define: {
                global: 'globalThis',
            },
            optimizeDeps: {
                include: ['buffer'],
                // @posthog/brand's png stubs locate their image via new URL(..., import.meta.url);
                // prebundling into .vite/deps would break that relative resolution. The package is
                // pure ESM, so serving it unbundled is safe, and Vite's build handles the URL
                // pattern natively.
                exclude: ['@posthog/brand'],
                rolldownOptions: {
                    plugins: [zodJitlessPlugin()],
                },
            },
            build: {
                rollupOptions: {
                    onwarn(warning: Rollup.RollupLog, defaultHandler: (warning: Rollup.RollupLog) => void) {
                        // "use client" directives from RSC-oriented deps (framer-motion, radix)
                        // are meaningless here, and barrel-file re-export cycles are endemic to
                        // the app's index.ts files. Together they bury real warnings in ~1000
                        // lines of noise per CI build.
                        if (
                            warning.code === 'MODULE_LEVEL_DIRECTIVE' ||
                            warning.code === 'CYCLIC_CROSS_CHUNK_REEXPORT'
                        ) {
                            return
                        }
                        defaultHandler(warning)
                    },
                },
            },
        }),

    docs: {
        autodocs: 'tag',
    },
}

export default config
