/* global module */
module.exports = {
    plugins: [
        '@babel/plugin-transform-runtime',
        '@babel/plugin-transform-react-jsx',
        '@babel/plugin-proposal-class-properties',
        'react-hot-loader/babel',
        ['babel-plugin-kea', { path: './frontend/src' }],
    ],
    presets: ['@babel/preset-env', '@babel/typescript'],
}
