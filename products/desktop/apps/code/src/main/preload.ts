import { exposeElectronTRPC } from "@posthog/electron-trpc/main";
import { contextBridge, webUtils } from "electron";
import "electron-log/preload";
import { parseSessionIdArg } from "./posthog-session-arg";

const DEV_FLAGS_CLI_PREFIX = "--posthog-code-flags=";

function readDevFlags(): { devMode: boolean } {
  const arg = process.argv.find((a) => a.startsWith(DEV_FLAGS_CLI_PREFIX));
  if (!arg) return { devMode: false };
  try {
    const payload = decodeURIComponent(arg.slice(DEV_FLAGS_CLI_PREFIX.length));
    const parsed = JSON.parse(payload);
    return { devMode: parsed?.devMode === true };
  } catch {
    return { devMode: false };
  }
}

const devFlags = readDevFlags();

contextBridge.exposeInMainWorld("electronUtils", {
  getPathForFile: (file: File) => webUtils.getPathForFile(file),
});

contextBridge.exposeInMainWorld("__posthogBootstrap", {
  sessionId: parseSessionIdArg(process.argv),
});

contextBridge.exposeInMainWorld("__posthogDevFlags", devFlags);

if (process.argv.includes("--posthog-code-dev")) {
  contextBridge.exposeInMainWorld("__posthogTest", {
    crash: () => {
      process.crash();
    },
    abort: () => {
      process.abort();
    },
  });
}

process.once("loaded", async () => {
  exposeElectronTRPC();
});
