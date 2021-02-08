const webpackPreprocessor = require('@cypress/webpack-preprocessor')

const mainConfig = require('../../webpack.config')()

module.exports = (on, config) => {
    const options = {
        webpackOptions: mainConfig[0],
        watchOptions: {},
    }

    on('file:preprocessor', webpackPreprocessor(options))
    try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        require('cypress-terminal-report/src/installLogsPrinter')(on)
    } catch (e) {}

    return config
}
