/** @type {import('postcss-load-config').Config} */
const config = {
    // This file is only for Webpack, which is still in use by Storybook
    // Sync the plugins list with utils.mjs
    plugins: [
        require('@tailwindcss/postcss'),
        require('autoprefixer'),
        require('postcss-preset-env')({ stage: 0 }),
        require('@csstools/postcss-gamut-mapping'),
        require('cssnano')({ preset: 'default' }),
    ],
}

module.exports = config
