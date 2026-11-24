import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  test: {
    ...trunkTestOptions,
    environment: "node",
    setupFiles: ["../workspace-server/src/test/saved-gateway-listing.ts"],
    include: ["src/**/*.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
  },
});
