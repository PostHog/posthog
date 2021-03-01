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

    on('before:browser:launch', (browser, launchOptions) => {
        if (browser.name === 'chrome') {
            // https://www.ghacks.net/2013/10/06/list-useful-google-chrome-command-line-switches/
            // Compatibility with gh actions
            launchOptions.args.push('--window-size=1280,720')
            return launchOptions
        }
    })

    return config
}
