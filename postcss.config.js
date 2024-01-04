/** @type {import('postcss-load-config').Config} */
const config = {
    plugins: [
        require('tailwindcss'),
        require('autoprefixer'),
        require('postcss-preset-env')({ stage: 0 }),
        require('cssnano')({ preset: 'default' }),
    ],
}

module.exports = config
