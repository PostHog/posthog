const { getJestConfig } = require('@storybook/test-runner')
const path = require('path')

const baseConfig = getJestConfig()

/**
 * @type {import('@jest/types').Config.InitialOptions}
 */
module.exports = {
    ...baseConfig,
    /** Add your own overrides below
     * @see https://jestjs.io/docs/configuration
     */
    forceExit: true,
    // Merge upstream reporters (includes jest-junit when --junit is passed)
    // with jest-image-snapshot's outdated snapshot reporter
    reporters: [...(baseConfig.reporters || ['default']), 'jest-image-snapshot/src/outdated-snapshot-reporter.js'],
    testEnvironment: './test-runner-jest-environment.js',
    snapshotResolver: './test-snapshot-resolver.js',
    testPathIgnorePatterns: ['/node_modules/', '/rust/cymbal/tests/snapshots/'],
    testSequencer: path.resolve(__dirname, 'test-sequencer.js'),
}
