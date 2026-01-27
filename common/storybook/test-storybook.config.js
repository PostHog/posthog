/**
 * Storybook test-runner configuration.
 *
 * This config customizes Jest to exclude the rust/ directory from snapshot scanning
 * to prevent Rust test snapshots from being detected as "obsolete" during
 * Storybook visual regression tests.
 *
 * @see https://storybook.js.org/docs/writing-tests/test-runner#ejecting-configuration
 */
const { getJestConfig } = require('@storybook/test-runner')

module.exports = {
    getJestConfig: () => {
        const config = getJestConfig()
        // Exclude rust/ directory from Jest's module scanning to prevent
        // Rust test snapshots from being detected as obsolete
        config.modulePathIgnorePatterns = [
            ...(config.modulePathIgnorePatterns || []),
            '<rootDir>/../../rust/',
        ]
        return config
    },
}
