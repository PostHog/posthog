module.exports = {
    transform: {
        '^.+\\.(t|j)s$': ['@swc/jest'],
    },
    testEnvironment: 'node',
    clearMocks: true,
    coverageProvider: 'v8',
    setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
    testMatch: ['<rootDir>/**/*.test.ts'],
    testTimeout: 60000,
}
