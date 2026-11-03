// Runs kea's own jest suite (copied from keajs/kea, test/jest) against this package.
// KEA_TEST_TARGET=original runs the same suite against the kea@4.0.0-pre.6 source, as a baseline.
const fs = require('fs')
const path = require('path')

const repo = path.resolve(__dirname, '../..')
const frontendModules = path.join(repo, 'frontend/node_modules')
const pnpmStore = path.join(repo, 'node_modules/.pnpm')
const keaDir = fs.readdirSync(pnpmStore).find((d) => /^kea@4\.0\.0-pre\.6/.test(d))
const keaDeps = path.join(pnpmStore, keaDir, 'node_modules')
const target =
    process.env.KEA_TEST_TARGET === 'original' ? path.join(keaDeps, 'kea/src') : path.join(__dirname, 'src')

module.exports = {
    rootDir: __dirname,
    testMatch: ['<rootDir>/test/jest/*.js', '<rootDir>/test/differential/*.test.js'],
    testEnvironment: path.join(frontendModules, 'jest-environment-jsdom'),
    setupFiles: ['<rootDir>/test/jest-polyfills.js'],
    setupFilesAfterEnv: ['<rootDir>/test/jest-setup.js'],
    transform: { '\\.[cm]?[jt]sx?$': path.join(frontendModules, '@sucrase/jest-plugin') },
    transformIgnorePatterns: ['/node_modules/(?!(\\.pnpm/kea@[^/]+/node_modules/kea/src|kea/src)/)'],
    moduleNameMapper: {
        '^\\.\\./\\.\\./src(.*)$': `${target}$1`,
    },
    // The package is not a pnpm workspace member. Resolve React and the test libraries from the
    // frontend, and redux and reselect from kea's own dependencies.
    // KEA_TEST_EXTRA_MODULES can point at a directory with react-test-renderer for snapshot.js.
    modulePaths: [frontendModules, keaDeps, ...(process.env.KEA_TEST_EXTRA_MODULES ? [process.env.KEA_TEST_EXTRA_MODULES] : [])],
}
