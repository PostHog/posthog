const plugins = [require('postcss-advanced-variables')(), require('postcss-nested')(), require('autoprefixer')()]

if (process.env.NODE_ENV === 'production') {
    plugins.push(require('cssnano'))
}

module.exports = {
    // syntax: 'postcss-scss',
    parser: 'postcss-scss',
    plugins,
    processors: [require('postcss-strip-inline-comments')],
}
