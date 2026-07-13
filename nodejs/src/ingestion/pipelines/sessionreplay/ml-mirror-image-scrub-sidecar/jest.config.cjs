module.exports = {
    testEnvironment: 'node',
    testMatch: ['<rootDir>/src/**/*.test.ts'],
    // The sources import each other with explicit `.ts` extensions (tsx style); strip the extension so
    // jest resolves the .ts file (moduleFileExtensions includes 'ts' by default).
    moduleNameMapper: {
        '^(\\.{1,2}/.*)\\.ts$': '$1',
    },
}
