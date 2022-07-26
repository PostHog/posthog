/* eslint-env node */

const plugins = [require('tailwindcss'), require('autoprefixer')] // postCSS modules here

if (process.env.NODE_ENV === 'production') {
    plugins.push(require('cssnano'))
}

module.exports = {
    plugins,
}
