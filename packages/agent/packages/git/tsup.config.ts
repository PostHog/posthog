import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/**/*.ts", "!src/**/*.test.ts"],
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  // One module instance across entries, so class identity survives mixed barrel and subpath imports.
  splitting: true,
  outDir: "dist",
  target: "node20",
});
