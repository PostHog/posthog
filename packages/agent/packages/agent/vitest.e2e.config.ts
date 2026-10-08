import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

// Live e2e suite. Separate from the default `vitest.config.ts` (which only
// includes `src/**`), so `pnpm test` never runs it. The `e2e` job in
// desktop-test.yml runs it on a branch that changes packages/agent/ or products/desktop/packages/,
// and skips it in the merge queue. Run it by hand with `pnpm test:e2e`.
// Sequential, generous timeouts: each test drives two real model turns end to end.
export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
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
