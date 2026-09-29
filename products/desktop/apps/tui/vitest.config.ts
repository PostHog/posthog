import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  test: {
    ...trunkTestOptions,
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // Components read and write ~/.config/posthog-tui, so tests get their own home.
    env: { HOME: mkdtempSync(join(tmpdir(), "posthog-tui-home-")) },
  },
});
