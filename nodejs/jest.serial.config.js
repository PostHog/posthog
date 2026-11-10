const config = require('./jest.config.shared')

module.exports = {
    ...config,
    testMatch: ['<rootDir>/tests/**/*.serial.test.ts', '<rootDir>/src/**/*.serial.test.ts'],
    testSequencer: '<rootDir>/jest.serial.sequencer.js',
}
