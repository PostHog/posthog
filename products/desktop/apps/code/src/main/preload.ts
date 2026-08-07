import { exposeElectronTRPC } from "@posthog/electron-trpc/main";
import { contextBridge, ipcRenderer, webUtils } from "electron";
import "electron-log/preload";
import { ARTIFACT_PREVIEW_ARG } from "../shared/constants";
import { parseSessionIdArg } from "./posthog-session-arg";

const DEV_FLAGS_CLI_PREFIX = "--posthog-code-flags=";
const ARTIFACT_BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";
const HOST_TO_ARTIFACT_CHANNEL = "posthog-artifact-host-message";
const ARTIFACT_TO_HOST_CHANNEL = "posthog-artifact-message";

function setupArtifactPreviewPreload(): void {
  window.addEventListener("message", (event) => {
    const data = event.data as Record<string, unknown> | null;
    if (data?.marker !== ARTIFACT_BRIDGE_MARKER) return;
    ipcRenderer.sendToHost(ARTIFACT_TO_HOST_CHANNEL, data);
  });

  ipcRenderer.on(HOST_TO_ARTIFACT_CHANNEL, (_event, data: unknown) => {
    window.postMessage(data, "*");
  });
}

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

function setupApplicationPreload(): void {
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
}

if (process.argv.includes(ARTIFACT_PREVIEW_ARG)) {
  setupArtifactPreviewPreload();
} else {
  setupApplicationPreload();
}
