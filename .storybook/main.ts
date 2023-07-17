import type { StorybookConfig } from '@storybook/react/types'
import { createEntry } from '../webpack.config'
const config: StorybookConfig = {
    stories: ['../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)'],
    addons: [
        {
            name: '@storybook/addon-docs',
            options: {
                sourceLoaderOptions: {
                    injectStoryParameters: false,
                },
            },
        },
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
        'storybook-addon-pseudo-states',
        '@storybook/addon-mdx-gfm',
    ],
    staticDirs: ['public'],
    webpackFinal: (config) => {
        const mainConfig = createEntry('main')
        return {
            ...config,
            resolve: {
                ...config.resolve,
                extensions: [...config.resolve!.extensions!, ...mainConfig.resolve.extensions],
                alias: {
                    ...config.resolve!.alias,
                    ...mainConfig.resolve.alias,
                },
            },
            module: {
                ...config.module,
                rules: [
                    ...mainConfig.module.rules,
                    ...config.module!.rules.filter((rule) => rule.test!.toString().includes('.mdx')),
                    {
                        test: /\.stories\.tsx?$/,
                        use: [
                            {
                                loader: require.resolve('@storybook/source-loader'),
                                options: {
                                    parser: 'typescript',
                                },
                            },
                        ],
                        enforce: 'pre',
                    },
                ],
            },
        }
    },
    features: {
        postcss: false,
    },
    framework: {
        name: '@storybook/react-webpack5',
        options: {},
    },
    docs: {
        autodocs: true,
    },
}
export default config
