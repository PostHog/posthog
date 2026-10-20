import { exposeElectronTRPC } from "@posthog/electron-trpc/main";
import { contextBridge, ipcRenderer, webUtils } from "electron";
import { sanitizeArtifactBridgeMessage } from "../shared/artifact-preview-message";
import {
  APP_WINDOW_ARG,
  ARTIFACT_HOST_TO_PREVIEW_CHANNEL,
  ARTIFACT_OPEN_EXTERNAL_CHANNEL,
  ARTIFACT_PREVIEW_TO_HOST_CHANNEL,
} from "../shared/constants";
import { trustedArtifactLink } from "./artifact-preview-link";
import { parseSessionIdArg } from "./posthog-session-arg";

const DEV_FLAGS_CLI_PREFIX = "--posthog-code-flags=";

function setupArtifactPreviewPreload(): void {
  document.addEventListener(
    "click",
    (event) => {
      const href = trustedArtifactLink(event);
      if (!href) return;
      event.preventDefault();
      event.stopPropagation();
      ipcRenderer.sendToHost(ARTIFACT_OPEN_EXTERNAL_CHANNEL, href);
    },
    true,
  );

  window.addEventListener("message", (event) => {
    const message = sanitizeArtifactBridgeMessage(event.data);
    if (
      !message ||
      (message.type === "selection" &&
        navigator.userActivation?.isActive !== true)
    ) {
      return;
    }
    ipcRenderer.sendToHost(ARTIFACT_PREVIEW_TO_HOST_CHANNEL, message);
  });

  ipcRenderer.on(ARTIFACT_HOST_TO_PREVIEW_CHANNEL, (_event, data: unknown) => {
    window.postMessage(data, "*");
  });
}

function readDevFlags(argv: string[]): { devMode: boolean } {
  const arg = argv.find((a) => a.startsWith(DEV_FLAGS_CLI_PREFIX));
  if (!arg) return { devMode: false };
  try {
    const payload = decodeURIComponent(arg.slice(DEV_FLAGS_CLI_PREFIX.length));
    const parsed = JSON.parse(payload);
    return { devMode: parsed?.devMode === true };
  } catch {
    return { devMode: false };
  }
}

function setupApplicationPreload(argv: string[]): void {
  void import("electron-log/preload");
  const devFlags = readDevFlags(argv);

  contextBridge.exposeInMainWorld("electronUtils", {
    getPathForFile: (file: File) => webUtils.getPathForFile(file),
  });

  contextBridge.exposeInMainWorld("__posthogBootstrap", {
    sessionId: parseSessionIdArg(argv),
  });

  contextBridge.exposeInMainWorld("__posthogDevFlags", devFlags);

  if (argv.includes("--posthog-code-dev")) {
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

export function setupPreload(argv: string[]): void {
  if (argv.includes(APP_WINDOW_ARG)) {
    setupApplicationPreload(argv);
  } else {
    setupArtifactPreviewPreload();
  }
}

setupPreload(process.argv);
