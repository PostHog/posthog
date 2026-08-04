import { defineConfig } from "@playwright/test";

// Dedicated config for the macOS chained auto-update E2E (a newer update
// re-staged over an already staged one). The general suite excludes update
// specs by path, so this only runs here and cannot silently skip. retries are
// 0 so a broken re-stage surfaces immediately. In CI the JSON reporter lets
// the workflow assert exactly one test actually ran.
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/update-chain.spec.ts",
  timeout: 60000,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["json"]] : [["list"]],
  outputDir: "../playwright-results",
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
