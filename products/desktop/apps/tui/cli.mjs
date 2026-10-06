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
// A crash skips the app's teardown, so turn off mouse reports, kitty keys and the alternate screen here too.
process.once("exit", () => {
  if (process.stdout.isTTY)
    process.stdout.write("\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[<u\x1b[?1049l");
});
// Ctrl+R in the app: throw away every loaded module and run the app again from disk.
globalThis.__posthogTuiReload = () =>
  server.environments.ssr.hot.send({ type: "full-reload" });

// An edit that breaks loading (a missing export, a syntax error) must not end the process: it holds the local
// agents, which may be the very session making the edit. Show the error and load again after the next save.
const appMounted = () => globalThis.__posthogTuiMounted === true;
const showFailure = (error) => {
  const detail =
    error instanceof Error ? (error.stack ?? error.message) : String(error);
  appendFileSync(
    LOG_PATH,
    `${new Date().toISOString()} error [load] ${detail}\n`,
  );
  if (appMounted() || !process.stdout.isTTY) return;
  const message = error instanceof Error ? error.message : String(error);
  process.stdout.write(
    `\x1b[2J\x1b[H The TUI failed to load: ${message}\r\n\r\n` +
      ` Save a fix and it loads again. Local agents keep running. The log is at ${LOG_PATH}.\r\n` +
      " Ctrl+C quits.\r\n",
  );
};
const start = () => runner.import("/src/main.tsx").catch(showFailure);
process.on("unhandledRejection", showFailure);
process.on("uncaughtException", showFailure);
// After an edit settles, a screen with no app on it means the reload failed, so try again from disk.
let retry = null;
server.watcher.on("change", () => {
  clearTimeout(retry);
  retry = setTimeout(() => {
    if (appMounted()) return;
    runner.clearCache();
    void start();
  }, 1_000);
});
await start();
