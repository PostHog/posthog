const path = require("node:path");
const { getJestConfig } = require("@storybook/test-runner");

const baseConfig = getJestConfig();

module.exports = {
  ...baseConfig,
  forceExit: true,
  // test-runner-globals.js must come first: Storybook 10 loads test-runner.ts
  // outside Jest's module scope, so `jest` has to be reachable via globalThis
  // for setup() to call jest.retryTimes / jest.setTimeout.
  setupFilesAfterEnv: [
    path.resolve(__dirname, "test-runner-globals.js"),
    ...(baseConfig.setupFilesAfterEnv ?? []),
  ],
  testTimeout: 60000,
  testEnvironment: path.resolve(__dirname, "test-runner-jest-environment.mjs"),
};
