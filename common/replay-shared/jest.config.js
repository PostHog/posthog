module.exports = {
    transform: {
        '^.+\\.[cm]?[jt]s$': ['@swc/jest'],
    },
    // posthog-js's rrweb subpath entries are shipped as ESM; let them through to the transform.
    transformIgnorePatterns: ['node_modules/(?!.*posthog-js/dist/rrweb)'],
    testEnvironment: 'node',
    clearMocks: true,
    testMatch: ['<rootDir>/src/**/*.test.ts'],
    // CI sets JEST_JUNIT_OUTPUT_DIR to collect junit for the Trunk quarantine gate.
    reporters: process.env.JEST_JUNIT_OUTPUT_DIR ? ['default', 'jest-junit'] : ['default'],
}
