module.exports = {
    transform: {
        '^.+\\.(t|j)s$': ['@swc/jest'],
    },
    testEnvironment: 'node',
    clearMocks: true,
    coverageProvider: 'v8',
    setupFilesAfterEnv: ['./jest.setup.js'],
    testMatch: ['<rootDir>/tests/**/*.test.ts', '<rootDir>/src/**/*.test.ts'],
    testTimeout: 60000,
    modulePathIgnorePatterns: ['<rootDir>/.tmp/'],

    // NOTE: This should be kept in sync with tsconfig.json
    moduleNameMapper: {
        '^~/tests/(.*)$': '<rootDir>/tests/$1',
        '^~/(.*)$': '<rootDir>/src/$1',
    },
}
