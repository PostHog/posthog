/**
 * Jest configuration for Storybook test-runner.
 *
 * This config excludes the rust/ directory from Jest's snapshot scanning
 * to prevent Rust test snapshots from being detected as "obsolete" during
 * Storybook visual regression tests.
 *
 * @see https://storybook.js.org/docs/writing-tests/test-runner#configure
 */
module.exports = {
    testPathIgnorePatterns: ['/node_modules/', '<rootDir>/../../rust/'],
}
