const webpackPreprocessor = require('@cypress/webpack-preprocessor')
const { initPlugin } = require('cypress-plugin-snapshots/plugin')

const { createEntry } = require('../../webpack.config')

module.exports = (on, config) => {
    const options = {
        webpackOptions: createEntry('cypress'),
        watchOptions: {},
    }

    on('file:preprocessor', webpackPreprocessor(options))
    try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        require('cypress-terminal-report/src/installLogsPrinter')(on)
    } catch (e) {}

    initPlugin(on, config)

    return config
}
