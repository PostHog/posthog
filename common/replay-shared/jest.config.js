module.exports = {
    transform: {
        '^.+\\.ts$': ['@swc/jest'],
    },
    testEnvironment: 'node',
    clearMocks: true,
    testMatch: ['<rootDir>/src/**/*.test.ts'],
}
