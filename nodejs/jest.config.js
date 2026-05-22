module.exports = {
    transform: {
        '^.+\\.(t|j)s$': [
            'ts-jest',
            {
                tsconfig: './tsconfig.test.json',
            },
        ],
    },
    testEnvironment: 'node',
    clearMocks: true,
    coverageProvider: 'v8',
    setupFilesAfterEnv: ['./jest.setup.ts'],
    testMatch: ['<rootDir>/tests/**/*.test.ts', '<rootDir>/src/**/*.test.ts'],
    testTimeout: 60000,
    modulePathIgnorePatterns: ['<rootDir>/.tmp/'],

    // NOTE: This should be kept in sync with tsconfig.json
    moduleNameMapper: {
        '^~/tests/(.*)$': '<rootDir>/tests/$1',
        '^~/(.*)$': '<rootDir>/src/$1',
        // Strip .js from relative imports so Jest resolves to the .ts source.
        // Production tsconfig is module: nodenext, which forces relative import()
        // specifiers to carry .js extensions (TS2835). ts-jest emits those strings
        // verbatim, but no .js file exists on disk, so the mapper rewrites the
        // request before Jest's resolver runs.
        '^(\\.{1,2}/.*)\\.js$': '$1',
    },
}
