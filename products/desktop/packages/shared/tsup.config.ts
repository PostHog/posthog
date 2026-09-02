import { defineConfig } from "tsup";

export default defineConfig({
  entry: [
    "src/index.ts",
    "src/analytics-events.ts",
    "src/announcements.ts",
    "src/constants.ts",
    "src/deeplink.ts",
    "src/dismissalReasons.ts",
    "src/domain-types.ts",
    "src/mcp-sandbox-proxy.ts",
    "src/posthog-property-headers.ts",
    "src/product-engineer-prompt.ts",
    "src/quick-ask-shortcuts.ts",
    "src/rich-output-prompt.ts",
    "src/types.ts",
  ],
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  splitting: false,
  outDir: "dist",
  target: "node20",
});
