import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

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
    include: ["src/**/*.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
    isolate: true,
    fileParallelism: false,
    // Session options write a settings file under the Claude config dir.
    env: { CLAUDE_CONFIG_DIR: resolve(tmpdir(), "posthog-agent-test-claude") },
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      exclude: ["node_modules/", "**/*.d.ts", "**/*.config.*"],
    },
  },
});
