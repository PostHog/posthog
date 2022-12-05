module.exports = {
    transform: {
        '^.+\\.(t|j)s$': [
            '@swc/jest',
            {
                jsc: {
                    target: 'es2021',
                },
                sourceMaps: true,
            },
        ],
    },
    coverageProvider: 'v8',
    testEnvironment: 'node',
    testMatch: ['<rootDir>/functional_tests/**/*.test.ts'],
    setupFilesAfterEnv: ['<rootDir>/functional_tests/jest.setup.ts'],
    globalTeardown: '<rootDir>/functional_tests/jest.global-teardown.ts',
    testTimeout: 60000,
    maxConcurrency: 10,
    maxWorkers: 6,
}
