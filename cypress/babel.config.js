/* global module */
module.exports = {
    plugins: [
        '@babel/plugin-transform-runtime',
        '@babel/plugin-transform-class-properties',
        '@babel/plugin-transform-private-property-in-object',
        '@babel/plugin-transform-nullish-coalescing-operator',
    ],
    presets: [
        [
            '@babel/preset-env',
            {
                useBuiltIns: 'usage',
                corejs: 3,
                targets: 'defaults', // browserlist's defaults - https://github.com/browserslist/browserslist#full-list
            },
        ],
        [
            '@babel/preset-react',
            {
                runtime: 'automatic',
            },
        ],
        '@babel/typescript',
    ],
}
