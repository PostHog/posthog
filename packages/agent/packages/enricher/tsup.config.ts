import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: false,
  splitting: false,
  outDir: "dist",
  target: "node20",
  external: ["web-tree-sitter"],
});
