// Storybook 10 loads .storybook/test-runner.ts via its own serverRequire,
// outside Jest's module scope, so the injected `jest` object must be exposed
// on globalThis for the test-runner config's setup() hook to reach it.
globalThis.jest = jest;
