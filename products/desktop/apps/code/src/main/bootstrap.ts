/**
 * Bootstrap entry point — the single place that knows about electron AND the
 * env-var boundary used by utility singletons.
 *
 * Runs BEFORE any service / util is imported. Sets:
 *   1. app name + custom userData path (needed for single-instance lock, stores, etc.)
 *   2. env vars that utility singletons (utils/logger, utils/env, utils/store,
 *      utils/fixPath, utils/otel-log-transport, services/settingsStore) read
 *      at module load. These utils do NOT import from "electron" — they only
 *      read from process.env, which keeps them portable.
 *
 * Static import of utils/fixPath is safe because fixPath reads process.env at
 * CALL time, not at module load. The main app body loads via dynamic
 * `import("./index.js")` so env vars are guaranteed to be set first.
 */

import dns from "node:dns";
import { mkdirSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { app, crashReporter, protocol } from "electron";
import { fixPath } from "./utils/fixPath";
import { shouldRefuseInternalChildBoot } from "./utils/internal-child-guard";

// The internal-child marker means a workspace-server descendant stripped
// ELECTRON_RUN_AS_NODE and ran `node` or process.execPath; booting a full app
// here would race the single-instance lock and open phantom windows.
if (shouldRefuseInternalChildBoot(app.isPackaged, process.env)) {
  process.stderr.write(
    "[posthog-code] Refusing to start the desktop app from inside its own " +
      "child process tree (expected ELECTRON_RUN_AS_NODE=1).\n",
  );
  process.exit(1);
}

const isDev = !app.isPackaged;

// Set app name for single-instance lock, crashReporter, etc
const appName = isDev ? "posthog-code-dev" : "posthog-code";
app.setName(isDev ? "PostHog (Development)" : "PostHog");

// Set userData path for @posthog/code
const appDataPath = app.getPath("appData");
const userDataPath =
  process.env.POSTHOG_E2E_USER_DATA_DIR ??
  path.join(appDataPath, "@posthog", appName);
app.setPath("userData", userDataPath);

// Export the electron-derived state to env so utility singletons (utils/*,
// services/settingsStore) can read it without importing from "electron".
// MUST happen before any project module evaluates code that reads these.
process.env.POSTHOG_CODE_DATA_DIR = userDataPath;
process.env.POSTHOG_CODE_IS_DEV = String(isDev);
process.env.POSTHOG_CODE_VERSION = app.getVersion();

// Enable Chromium internal logging to a dedicated file. Without this, Chromium
// crashes (black screens, render-process-gone, GPU process death) leave no
// trail because Electron silently swallows the underlying logs. Must run
// before app.whenReady() so the switches take effect on the GPU/renderer
// child processes.
const chromiumLogDir = path.join(
  os.homedir(),
  ".posthog-code",
  isDev ? "logs-dev" : "logs",
);
mkdirSync(chromiumLogDir, { recursive: true });
const chromiumLogPath = path.join(chromiumLogDir, "chromium.log");
process.env.ELECTRON_ENABLE_LOGGING = "1";
process.env.POSTHOG_CODE_CHROMIUM_LOG_PATH = chromiumLogPath;
app.commandLine.appendSwitch("enable-logging", "file");
app.commandLine.appendSwitch("log-file", chromiumLogPath);
app.commandLine.appendSwitch("log-level", "0");

// Allow programmatic audio playback without a prior user gesture. The agent
// speaks (and completion sounds ring) autonomously, with no click at that
// moment, so Chromium's default gesture requirement would silently reject
// HTMLMediaElement.play(). Must be set before app "ready".
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

// In dev, expose the renderer over CDP (:9222 by default) for the
// test-electron-app skill. electron-vite launches Electron itself, so this is
// set in-process rather than via a CLI flag. POSTHOG_CODE_CDP_PORT matches the
// port resolution in scripts/electron-cdp.mjs, for when :9222 is taken.
if (isDev) {
  app.commandLine.appendSwitch(
    "remote-debugging-port",
    process.env.POSTHOG_CODE_CDP_PORT ?? "9222",
  );
}

crashReporter.start({ uploadToServer: false });

// Force IPv4 resolution when "localhost" is used so the agent hits 127.0.0.1
// instead of ::1. This matches how the renderer already reaches the PostHog API.
dns.setDefaultResultOrder("ipv4first");

// Disable "Happy Eyeballs": PostHog's many-address ELB times out the connect
// when IPv6 is unreachable (e.g. Tailscale), as family racing abandons each
// IPv4 attempt before it completes. ipv4first alone isn't enough.
net.setDefaultAutoSelectFamily(false);

// Call fixPath early to ensure PATH is correct for any child processes
fixPath();

// Register mcp-sandbox: protocol scheme for MCP Apps iframe isolation.
// Must be called before app.ready — gives the sandbox proxy its own origin
// so MCP Apps can't access the renderer's DOM, storage, or cookies.
protocol.registerSchemesAsPrivileged([
  {
    scheme: "mcp-sandbox",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: false,
    },
  },
]);

// Now dynamically import the rest of the application.
// Dynamic import ensures env vars are set BEFORE index.js is evaluated —
// static imports are hoisted and would run before our process.env writes.
import("./index.js");
