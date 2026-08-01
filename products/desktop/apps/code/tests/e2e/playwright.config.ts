import { defineConfig } from "@playwright/test";

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  // The update specs need a signed feed; they run only via their dedicated
  // configs (playwright.update*.config.ts), never in the general suite.
  testIgnore: "**/update*.spec.ts",
  timeout: 60000,
  // No retries: Trunk Flaky Tests needs raw pass/fail results to detect flakes.
  retries: 0,
  // Must run serially - Electron app has single instance lock
  workers: 1,
  // junit.xml (resolved next to this config) is uploaded to Trunk in CI.
  reporter: isCI
    ? [
        ["junit", { outputFile: "junit.xml" }],
        ["github"],
        ["html", { open: "never" }],
      ]
    : [["junit", { outputFile: "junit.xml" }], ["list"]],
  outputDir: "../playwright-results",
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "electron",
      testMatch: "**/*.spec.ts",
      testIgnore: "**/update*.spec.ts",
    },
  ],
});
