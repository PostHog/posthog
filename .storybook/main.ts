import { createEntry } from '../webpack.config'
import * as babelConfig from '../babel.config'

module.exports = {
    stories: ['../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)'],
    addons: [
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        './ApiSelector/register.js',
        {
            name: 'storybook-addon-turbo-build',
            options: {
                optimizationLevel: 3,
            },
        },
    ],
    staticDirs: ['public'],
    babel: async () => {
        // compile babel to "defaults" target (ES5)
        const envPreset = (babelConfig as any).presets.find(
            (preset: any) => Array.isArray(preset) && preset[0] === '@babel/preset-env'
        )
        envPreset[1].targets = 'defaults'
        return babelConfig
    },
    webpackFinal: (config: any) => {
        const mainConfig = createEntry('main')
        const newConfig: any = {
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
                    ...config.module.rules.filter((rule: any) => rule.test.toString().includes('.mdx')),
                ],
            },
        }
        return newConfig
    },
}
