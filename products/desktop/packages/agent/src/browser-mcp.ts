import { createRequire } from "node:module";
import path from "node:path";

export interface BrowserMcpServer {
  name: string;
  command: string;
  args: string[];
  env: Array<{ name: string; value: string }>;
}

const require = createRequire(import.meta.url);

export function createBrowserMcpServer(): BrowserMcpServer {
  const packageJson = require.resolve("chrome-devtools-mcp/package.json");

  return {
    name: "chrome-devtools",
    command: process.execPath,
    args: [
      path.join(
        path.dirname(packageJson),
        "build/src/bin/chrome-devtools-mcp.js",
      ),
      "--auto-connect",
      "--redact-network-headers",
      "--no-usage-statistics",
      "--no-performance-crux",
    ],
    env: [{ name: "ELECTRON_RUN_AS_NODE", value: "1" }],
  };
}
