import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  oxc: false,
  esbuild: {
    tsconfigRaw: {
      compilerOptions: {
        experimentalDecorators: true,
        target: "ES2022",
        useDefineForClassFields: false,
        verbatimModuleSyntax: true,
      },
    },
  },
  test: {
    globals: true,
    ...trunkTestOptions,
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    exclude: ["**/node_modules/**", "**/dist/**"],
  },
});
