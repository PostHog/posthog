module.exports = {
    transform: {
        '^.+\\.(t|j)s$': ['@swc/jest'],
    },
    testEnvironment: 'node',
    clearMocks: true,
    coverageProvider: 'v8',
    setupFilesAfterEnv: ['./jest.setup.fetch-mock.js'],
    globalSetup: './jest.global-setup.ts',
    globalTeardown: './jest.global-teardown.ts',
    testMatch: ['<rootDir>/tests/**/*.test.ts'],
    testTimeout: 60000,
}
