#!/usr/bin/env node
// The built app. `pnpm dev` (cli.mjs) runs the source through Vite instead, with hot reload.
import { readFileSync } from "node:fs";

// Answered before the app loads, so a release can smoke the installed bin without a terminal.
if (process.argv.includes("--version") || process.argv.includes("-v")) {
  const { version } = JSON.parse(
    readFileSync(new URL("./package.json", import.meta.url), "utf8"),
  );
  console.log(version);
  process.exit(0);
}
process.env.NODE_ENV ||= "production";
process.once("exit", () => {
  if (process.stdout.isTTY)
    process.stdout.write("\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[<u\x1b[?1049l");
});
await import("./dist/posthog-tui.mjs");
