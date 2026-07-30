import { defineConfig } from "tsup";

export default defineConfig({
  entry: [
    "src/index.ts",
    "src/agent-platform-types.ts",
    "src/analytics-events.ts",
    "src/constants.ts",
    "src/deeplink.ts",
    "src/dismissalReasons.ts",
    "src/domain-types.ts",
    "src/mcp-sandbox-proxy.ts",
    "src/posthog-property-headers.ts",
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
