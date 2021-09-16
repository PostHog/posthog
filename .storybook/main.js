const { createEntry } = require('../webpack.config')
const babelConfig = require('../babel.config')

module.exports = {
    stories: ['../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)'],
    addons: ['@storybook/addon-links', '@storybook/addon-essentials', './ApiSelector/register.js'],
    babel: async (options) => {
        // compile babel to "defaults" target (ES5)
        const envPreset = babelConfig.presets.find(
            (preset) => Array.isArray(preset) && preset[0] === '@babel/preset-env'
        )
        envPreset[1].targets = 'defaults'
        return babelConfig
    },
    webpackFinal: (config) => {
        const mainConfig = createEntry('main')
        const newConfig = {
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
                ],
            },
        }
        return newConfig
    },
}
