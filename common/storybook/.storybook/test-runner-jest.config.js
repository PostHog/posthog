const { getJestConfig } = require('@storybook/test-runner')

module.exports = {
    ...getJestConfig(),
    // Ignore rust directory to prevent finding unrelated snapshots
    modulePathIgnorePatterns: ['<rootDir>/../../rust'],
}
