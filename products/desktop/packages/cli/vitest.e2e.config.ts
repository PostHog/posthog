import { defineConfig } from "vitest/config";

// Live, opt-in smoke test for the built CLI binary. Separate from
// vitest.config.ts so it never runs under `pnpm test` — only via
// `pnpm test:e2e` with a gateway token set (same env contract as
// packages/agent/e2e). Each test spawns a real agent turn end to end.
export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["e2e/**/*.e2e.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
    isolate: true,
    fileParallelism: false,
    testTimeout: 300_000,
    hookTimeout: 120_000,
  },
});
