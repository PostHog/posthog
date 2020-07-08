/* eslint-disable @typescript-eslint/no-var-requires */
/* global require, module, process */

module.exports = {
    plugins:
        process.env.NODE_ENV === 'production'
            ? [
                  require('autoprefixer'),
                  require('cssnano'),
                  // More postCSS modules here if needed
              ]
            : [require('autoprefixer')],
}
