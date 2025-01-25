module.exports = {
    transform: {
        '^.+\\.(t|j)s$': ['@swc/jest'],
    },
    testEnvironment: 'node',
    clearMocks: true,
    coverageProvider: 'v8',
    testMatch: ['<rootDir>/**/*.test.ts'],
    testTimeout: 60000,
}
