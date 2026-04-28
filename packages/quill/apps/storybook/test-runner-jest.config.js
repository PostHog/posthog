const { getJestConfig } = require('@storybook/test-runner')

const baseConfig = getJestConfig()

/**
 * @type {import('@jest/types').Config.InitialOptions}
 */
module.exports = {
    ...baseConfig,
    forceExit: true,
    reporters: [...(baseConfig.reporters || ['default']), 'jest-image-snapshot/src/outdated-snapshot-reporter.js'],
    testTimeout: 30000,
}
