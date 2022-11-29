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
    testTimeout: 60000,
}
