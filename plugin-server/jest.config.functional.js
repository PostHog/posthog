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
    globalTeardown: '<rootDir>/functional_tests/jest.global-teardown.ts',
    testTimeout: 60000,
    maxConcurrency: 10,
    maxWorkers: 6,

    // NOTE: This should be kept in sync with tsconfig.json
    moduleNameMapper: {
        '^~/(.*)$': '<rootDir>/$1',
    },
}
