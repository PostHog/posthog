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
    // Run our globals bridge before the test-runner's own setup so its hooks can use `jest`.
    setupFilesAfterEnv: ['./common/storybook/test-runner-globals.js', ...(baseConfig.setupFilesAfterEnv || [])],
    testTimeout: 60000,
    testEnvironment: './common/storybook/test-runner-jest-environment.mjs',
    snapshotResolver: './common/storybook/test-snapshot-resolver.js',
    testPathIgnorePatterns: ['/node_modules/', '/rust/cymbal/tests/snapshots/'],
    testSequencer: path.resolve(__dirname, 'test-sequencer.js'),
}
