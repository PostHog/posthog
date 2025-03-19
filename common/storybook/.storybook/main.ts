import { createEntry } from '../webpack.config'
import type { StorybookConfig } from '@storybook/react-webpack5'

const config: StorybookConfig = {
    stories: [
        // Only include stories files, exclude MDX files temporarily — they cause the build to fail
        '../../../frontend/src/**/*.stories.@(js|jsx|ts|tsx)',
        '../../../products/**/frontend/**/*.stories.@(js|jsx|ts|tsx)',
        // Temporarily exclude MDX files that have function declarations
        // '../../../frontend/src/**/*.mdx',
        // '../../../products/**/frontend/**/*.mdx',
    ],

    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
        'storybook-addon-pseudo-states',
        '@storybook/addon-mdx-gfm',
    ],

    staticDirs: ['public', { from: '../../../frontend/public', to: '/static' }],

    webpackFinal: (config) => {
        const mainConfig = createEntry('main')

        // Create a copy of mainConfig's alias without any potential 'storybook' entries
        const safeAliases = { ...mainConfig.resolve.alias }
        delete safeAliases['storybook']

        return {
            ...config,
            resolve: {
                ...config.resolve,
                extensions: [...config.resolve!.extensions!, ...mainConfig.resolve.extensions],
                alias: {
                    ...config.resolve!.alias,
                    ...safeAliases,
                },
                fallback: {
                    ...(config.resolve?.fallback || {}),
                    path: require.resolve('path-browserify'),
                },
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
        options: { builder: {} },
    },

    docs: {
        defaultName: 'Documentation',
        autodocs: true,
    },

    typescript: { reactDocgen: 'react-docgen' },

    // Core options for better error handling
    core: {
        disableTelemetry: true,
        enableCrashReports: false,
    },
}

export default config
