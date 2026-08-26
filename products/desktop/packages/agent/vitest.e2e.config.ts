import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

// Live, opt-in e2e suite. Separate from the default `vitest.config.ts` (which
// only includes `src/**`), so these never run under `pnpm test` or per-PR CI;
// run them manually with `pnpm test:e2e` (no CI job invokes them). Sequential,
// generous timeouts: each test drives two real model turns end to end.
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
