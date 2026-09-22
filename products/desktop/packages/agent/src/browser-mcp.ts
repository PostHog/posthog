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
  const packageJson = require.resolve("@playwright/mcp/package.json");

  return {
    name: "browser",
    command: process.execPath,
    args: [path.join(path.dirname(packageJson), "cli.js"), "--extension"],
    env: [{ name: "ELECTRON_RUN_AS_NODE", value: "1" }],
  };
}
