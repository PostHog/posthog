import path from "node:path";
import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  test: {
    ...trunkTestOptions,
    environment: "node",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
