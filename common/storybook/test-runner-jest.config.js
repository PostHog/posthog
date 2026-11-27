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
    testEnvironmentOptions: {
        ...baseConfig.testEnvironmentOptions,
        'jest-playwright': {
            ...baseConfig.testEnvironmentOptions['jest-playwright'],
            launchOptions: {
                // Chromium re-rasters a partly changed tile in place, and its anti-aliased edge pixels then
                // differ from a full raster by a color level or two. Which tiles that hits depends on timing,
                // so the same story can give a different picture on each run. A per-browser key keeps the
                // Chromium-only switch away from WebKit.
                chromium: { args: ['--disable-partial-raster'] },
            },
        },
    },
    snapshotResolver: './common/storybook/test-snapshot-resolver.js',
    testPathIgnorePatterns: ['/node_modules/', '/rust/cymbal/tests/snapshots/'],
    testSequencer: path.resolve(__dirname, 'test-sequencer.js'),
}
