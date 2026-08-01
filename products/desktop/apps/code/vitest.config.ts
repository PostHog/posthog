import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";
import { rendererAliases } from "./vite.shared.mjs";

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify("test"),
  },
  test: {
    globals: true,
    ...trunkTestOptions,
    environment: "jsdom",
    setupFiles: ["./src/shared/test/setup.ts"],
    exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      exclude: [
        "node_modules/",
        "src/shared/test/",
        "**/*.d.ts",
        "**/*.config.*",
        "**/mockData.ts",
      ],
    },
  },
  resolve: {
    alias: [
      ...rendererAliases,
      {
        find: "@test",
        replacement: path.resolve(__dirname, "./src/shared/test"),
      },
    ],
  },
});
