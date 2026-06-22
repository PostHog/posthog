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
    setupFiles: ['./jest.setup-env.ts'],
    setupFilesAfterEnv: ['./jest.setup.ts'],
    testMatch: ['<rootDir>/tests/**/*.test.ts', '<rootDir>/src/**/*.test.ts'],
    testTimeout: 60000,
    modulePathIgnorePatterns: ['<rootDir>/.tmp/'],

    // NOTE: This should be kept in sync with tsconfig.json
    moduleNameMapper: {
        // `~/...` -> src/, `~/tests/...` -> tests/. The `.js`-suffixed variants come first to strip the
        // nodenext extension: the production tsconfig is module: nodenext, which forces import()
        // specifiers to carry `.js` (TS2835/TS2307), so ts-jest emits e.g. `~/foo.js` while only a
        // `.ts` exists on disk. Jest only strips `.js` from *relative* specifiers (last rule), not from
        // `~/` aliases — without these, an alias would resolve to a non-existent `src/foo.js`.
        '^~/tests/(.*)\\.js$': '<rootDir>/tests/$1',
        '^~/tests/(.*)$': '<rootDir>/tests/$1',
        '^~/(.*)\\.js$': '<rootDir>/src/$1',
        '^~/(.*)$': '<rootDir>/src/$1',
        // Strip .js from relative imports so Jest resolves to the .ts source.
        '^(\\.{1,2}/.*)\\.js$': '$1',
    },
}
