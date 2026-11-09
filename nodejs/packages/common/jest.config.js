const config = require('./jest.config.shared')

module.exports = {
    ...config,
    testMatch: ['<rootDir>/tests/**/*.test.ts', '<rootDir>/src/**/*.test.ts'],
}
