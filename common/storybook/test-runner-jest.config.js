const { getJestConfig } = require('@storybook/test-runner')

/**
 * @type {import('@jest/types').Config.InitialOptions}
 */
module.exports = {
    // The default configuration comes from @storybook/test-runner
    ...getJestConfig(),
    /** Add your own overrides below
     * @see https://jestjs.io/docs/configuration
     */
    // Ignore Rust snapshot files - they're for insta crate, not Jest
    testPathIgnorePatterns: ['/node_modules/', '<rootDir>/../../rust/'],
}
