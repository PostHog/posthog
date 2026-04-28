import type { StorybookConfig } from '@storybook/types'
import * as path from 'path'

import { createEntry } from '../webpack.config.js'
import { ModuleGraphPlugin } from './plugins/module-graph-plugin'

// Repo root = three levels up from this file (common/storybook/.storybook/main.ts).
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')

const config: StorybookConfig = {
    stories: [
        '../../../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../products/**/frontend/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../products/**/mcp/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../common/mosaic/storybook/**/*.stories.@(js|jsx|ts|tsx|mdx)',
    ],

    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
    ],

    staticDirs: [
        'public',
        { from: '../../../frontend/public', to: '/static' },
        { from: '../../../frontend/node_modules/@posthog/hedgehog-mode/assets', to: '/static/hedgehog-mode' },
    ],

    webpackFinal: (config) => {
        const mainConfig = createEntry('main')
        return {
            ...config,
            // Disable filesystem cache in CI to avoid heap OOM during cache shutdown
            // (especially on memory-constrained environments like Cloudflare Pages)
            cache: process.env.CI ? false : { type: 'filesystem' },
            plugins: [...(config.plugins ?? []), new ModuleGraphPlugin(REPO_ROOT)],
            resolve: {
                ...config.resolve,
                extensions: [...config.resolve!.extensions!, ...mainConfig.resolve.extensions],
                alias: { ...config.resolve!.alias, ...mainConfig.resolve.alias },
            },
            module: {
                ...config.module,
                rules: [
                    ...mainConfig.module.rules,
                    ...(config.module?.rules?.filter(
                        (rule: any) => 'test' in rule && rule.test.toString().includes('.mdx')
                    ) ?? []),
                ],
            },
        }
    },

    framework: {
        name: '@storybook/react-webpack5',
        options: { builder: { useSWC: true } },
    },

    build: {
        test: {
            disableSourcemaps: !!process.env.CI,
        },
    },

    docs: {
        autodocs: 'tag',
    },

    typescript: { reactDocgen: 'react-docgen' }, // Shouldn't be needed in Storybook 8
}

export default config
