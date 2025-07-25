import { createEntry } from '../webpack.config'
import { StorybookConfig } from '@storybook/react-webpack5'

const config: StorybookConfig = {
    stories: [
        '../../../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../products/**/frontend/**/*.stories.@(js|jsx|ts|tsx|mdx)',
    ],

    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
    ],

    staticDirs: ['public', { from: '../../../frontend/public', to: '/static' }],

    webpackFinal: (config) => {
        const mainConfig = createEntry('main')
        return {
            ...config,
            cache: {
                type: 'filesystem',
            },
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

    docs: {
        autodocs: 'tag',
    },

    typescript: { reactDocgen: 'react-docgen' }, // Shouldn't be needed in Storybook 8
}

export default config
