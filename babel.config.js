/* global module */
module.exports = {
    // We need both babel.config.js and .babelrc, because the former is required by Jest, while the latter by Storybook
    // See Storybook issue: https://github.com/storybookjs/storybook/issues/17398
    plugins: [
        '@babel/plugin-transform-runtime',
        '@babel/plugin-transform-react-jsx',
        '@babel/plugin-proposal-class-properties',
        '@babel/plugin-proposal-private-property-in-object',
    ],
    presets: [
        [
            '@babel/preset-env',
            {
                useBuiltIns: 'usage',
                corejs: 3,
            },
        ],
        '@babel/typescript',
    ],
}
