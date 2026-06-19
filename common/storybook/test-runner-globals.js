// Storybook 10 loads .storybook/test-runner.ts outside the Jest runtime (via
// serverRequire), so its setup/preVisit/postVisit hooks can't see Jest's
// per-module `jest` global and calls like jest.retryTimes / jest.setTimeout
// throw "jest is not defined". This CommonJS setup file IS loaded by Jest, so
// re-expose the runtime `jest` object on globalThis for those hooks. Must run
// before the test-runner's own setup hook (it is listed first in
// setupFilesAfterEnv).
const { jest } = require('@jest/globals')

globalThis.jest = jest
