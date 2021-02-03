// const preprocessor = require('@cypress/react/plugins/babelrc')

const webpackPreprocessor = require('@cypress/webpack-preprocessor')
const defaults = webpackPreprocessor.defaultOptions


const mainConfig = require('../../webpack.config')()

module.exports = (on, config) => {
    // preprocessor(on, config)
    // config.env.webpackFilename = 'webpack.config.js'
    // require('@cypress/react/plugins/load-webpack')(on, config)

    // delete defaults.webpackOptions.module.rules[0].use[0].options.presets
    const options = {
        webpackOptions: mainConfig[0],
        watchOptions: {},
    }

      console.log(options)

    on('file:preprocessor', webpackPreprocessor(options))
    // try {
    //     // eslint-disable-next-line @typescript-eslint/no-var-requires
    //     require('cypress-terminal-report/src/installLogsPrinter')(on)
    // } catch (e) {}

    return config
}
