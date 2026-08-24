import { resolve } from "node:path";
import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

// Live e2e suite. Separate from the default `vitest.config.ts` (which only
// includes `src/**`), so these never run under `pnpm test`. The `e2e` job in
// .github/workflows/desktop-test.yml runs them per PR (via `pnpm test:e2e`)
// when a products/desktop/packages/ file changes. Sequential, generous
// timeouts: each test drives real model turns end to end. `trunkTestOptions`
// writes ./junit.xml next to this config, which the job uploads to Trunk for
// flaky-test quarantine.
export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    globals: true,
    ...trunkTestOptions,
    environment: "node",
    include: ["e2e/**/*.e2e.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
    isolate: true,
    fileParallelism: false,
    testTimeout: 300_000,
    hookTimeout: 120_000,
  },
});
