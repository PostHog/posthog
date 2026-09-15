import { defineConfig } from "tsup";

const shared = {
  format: ["esm"],
  sourcemap: true,
  target: "node26",
};

export default defineConfig([
  {
    ...shared,
    entry: ["src/bin.ts"],
    clean: true,
    outDir: "dist",
    external: ["./app.js"],
  },
  {
    ...shared,
    entry: ["src/app.ts"],
    clean: false,
    outDir: "dist",
    external: ["@opentui/core"],
  },
]);
