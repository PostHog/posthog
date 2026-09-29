#!/usr/bin/env node
import { appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createLogger, createServer, createServerModuleRunner } from "vite";

// Runs the TUI through Vite so edits under src/ hot-swap into the running app.
const LOG_PATH = join(tmpdir(), "posthog-tui.log");
const logger = createLogger("info", { allowClearScreen: false });
// Ink owns the screen, so Vite's own output goes to the log file.
for (const level of ["info", "warn", "warnOnce", "error"]) {
  logger[level] = (message) =>
    appendFileSync(
      LOG_PATH,
      `${new Date().toISOString()} vite ${level} ${message}\n`,
    );
}

const server = await createServer({
  configFile: false,
  root: dirname(fileURLToPath(import.meta.url)),
  appType: "custom",
  customLogger: logger,
  server: { middlewareMode: true, ws: false },
});
const runner = createServerModuleRunner(server.environments.ssr, {
  hmr: { logger: false },
});
await runner.import("/src/main.tsx");
