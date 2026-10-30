#!/usr/bin/env node
// The built app. `pnpm dev` (cli.mjs) runs the source through Vite instead, with hot reload.
process.env.NODE_ENV ||= "production";
process.once("exit", () => {
  if (process.stdout.isTTY)
    process.stdout.write("\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[<u\x1b[?1049l");
});
await import("./dist/posthog-tui.mjs");
