/* global module */
module.exports = {
    plugins: [
        '@babel/plugin-transform-runtime',
        '@babel/plugin-transform-react-jsx',
        ['@babel/plugin-proposal-class-properties', { loose: true }],
        ['@babel/plugin-proposal-private-property-in-object', { loose: true }],
        ['babel-plugin-kea', { path: './frontend/src' }],
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
