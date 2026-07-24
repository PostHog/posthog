/// <reference types="vitest" />
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { trunkTestOptions } from "../../vitest.config.base";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    ...trunkTestOptions,
    coverage: {
      all: true,
      include: ["src/**/*"],
      reporter: ["text", "cobertura", "html"],
      reportsDirectory: path.resolve(__dirname, "./coverage/"),
    },
  },
});
