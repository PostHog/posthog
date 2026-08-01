import { defineConfig } from "@playwright/test";

// Dedicated config for the Forge -> electron-builder auto-update E2E. The general
// suite excludes update*.spec.ts by path, so this only runs here and cannot
// silently skip. retries are 0 so a broken swap surfaces immediately. In CI the
// JSON reporter lets the workflow assert exactly one test actually ran.
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/update-forge.spec.ts",
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
