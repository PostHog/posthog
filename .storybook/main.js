const { createEntry } = require('../webpack.config')

module.exports = {
    stories: ['../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)'],
    core: {
        builder: {
            name: 'webpack5',
            options: {
                fsCache: true,
            },
        },
    },
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
    ],
    staticDirs: ['public'],
    webpackFinal: (config) => {
        const mainConfig = createEntry('main')
        return {
            ...config,
            resolve: {
                ...config.resolve,
                extensions: [...config.resolve.extensions, ...mainConfig.resolve.extensions],
                alias: { ...config.resolve.alias, ...mainConfig.resolve.alias },
            },
            module: {
                ...config.module,
                rules: [
                    ...mainConfig.module.rules,
                    ...config.module.rules.filter((rule) => rule.test.toString().includes('.mdx')),
                    {
                        test: /\.stories\.tsx?$/,
                        use: [
                            {
                                loader: require.resolve('@storybook/source-loader'),
                                options: { parser: 'typescript' },
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
        storyStoreV7: true, // https://github.com/storybookjs/storybook/blob/next/MIGRATION.md#story-store-v7
        babelModeV7: true,
    },
}
