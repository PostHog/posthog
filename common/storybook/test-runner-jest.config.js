const { getJestConfig } = require('@storybook/test-runner')

/**
 * @type {import('@jest/types').Config.InitialOptions}
 */
module.exports = {
    // The default configuration comes from @storybook/test-runner
    ...getJestConfig(),
    forceExit: true,
    // For jest-image-snapshot, see https://github.com/americanexpress/jest-image-snapshot#removing-outdated-snapshots
    reporters: ['default', 'jest-image-snapshot/src/outdated-snapshot-reporter.js'],
    testEnvironment: '../../test-runner-jest-environment.js',
    // Block Jest from scanning rust/ directory entirely.
    // This prevents Rust test snapshots (*.snap files in rust/cymbal/tests/snapshots/)
    // from being detected as "obsolete" during Storybook visual regression tests.
    haste: {
        blockList: [/[\\/]rust[\\/]/],
    },
}
