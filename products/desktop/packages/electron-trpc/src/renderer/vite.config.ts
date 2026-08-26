/// <reference types="vitest" />
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "./",
  build: {
    sourcemap: true,
    emptyOutDir: false,
    lib: {
      entry: path.resolve(__dirname, "./index.ts"),
      name: "trpc-electron",
      formats: ["es"],
      fileName: () => "renderer.mjs",
    },
    outDir: path.resolve(__dirname, "../../dist"),
  },
});
