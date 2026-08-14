import { defineConfig, devices } from "@playwright/test";

const isCI = !!process.env.CI;
const PORT = 5273;
const BASE_URL = `http://localhost:${PORT}`;

// Browser e2e for the web host. Unlike apps/code (which drives Electron), this
// is a plain SPA, so it runs in stock Chromium against the Vite dev server.
// Scope is the hermetic happy path up to the OAuth wall: boot, container wiring,
// onboarding → sign-in, and the /callback relay. Real login needs PostHog cloud
// + a popup IdP, so it's out of scope here (see apps/web/README.md).
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  timeout: 60_000,
  // No retries: Trunk Flaky Tests needs raw pass/fail results to detect flakes.
  retries: 0,
  fullyParallel: true,
  forbidOnly: isCI,
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
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Boot the same dev server developers use. Reuse a running one locally so the
  // server we already spun up isn't fought over; always start fresh in CI.
  webServer: {
    command: "pnpm dev",
    url: BASE_URL,
    reuseExistingServer: !isCI,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
