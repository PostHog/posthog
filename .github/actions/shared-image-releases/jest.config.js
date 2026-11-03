module.exports = {
  clearMocks: true,
  roots: ['<rootDir>/src', '<rootDir>/__tests__', '<rootDir>/../paths-filter/src'],
  moduleFileExtensions: ['js', 'ts'],
  testEnvironment: 'node',
  testMatch: ['**/*.test.ts'],
  testRunner: 'jest-circus/runner',
  transform: {
    '^.+\\.ts$': 'ts-jest'
  },
  verbose: true
}
