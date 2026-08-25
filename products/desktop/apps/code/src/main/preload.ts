import { exposeElectronTRPC } from "@posthog/electron-trpc/main";
import { contextBridge, ipcRenderer, webUtils } from "electron";
import { sanitizeArtifactBridgeMessage } from "../shared/artifact-preview-message";
import {
  APP_WINDOW_ARG,
  ARTIFACT_HOST_TO_PREVIEW_CHANNEL,
  ARTIFACT_OPEN_EXTERNAL_CHANNEL,
  ARTIFACT_PREVIEW_TO_HOST_CHANNEL,
  QUICK_ASK_ANNOTATE_DONE_CHANNEL,
  QUICK_ASK_ANNOTATE_SHOT_CHANNEL,
  QUICK_ASK_ANNOTATE_WINDOW_ARG,
  QUICK_ASK_ASK_CHANNEL,
  QUICK_ASK_ATTACHMENT_CHANNEL,
  QUICK_ASK_CANCEL_CHANNEL,
  QUICK_ASK_CAPTURE_CHANNEL,
  QUICK_ASK_DISCARD_ATTACHMENT_CHANNEL,
  QUICK_ASK_DRAG_END_CHANNEL,
  QUICK_ASK_DRAG_START_CHANNEL,
  QUICK_ASK_EVENT_CHANNEL,
  QUICK_ASK_HIDE_CHANNEL,
  QUICK_ASK_LAYOUT_CHANNEL,
  QUICK_ASK_OPEN_IN_APP_CHANNEL,
  QUICK_ASK_RESET_CHANNEL,
  QUICK_ASK_RESIZE_CHANNEL,
  QUICK_ASK_SCREEN_SETTINGS_CHANNEL,
  QUICK_ASK_SHAKE_CHANNEL,
  QUICK_ASK_SHOWN_CHANNEL,
  QUICK_ASK_WINDOW_ARG,
  type QuickAskDragStartPayload,
  type QuickAskResizePayload,
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

function setupQuickAskPreload(): void {
  contextBridge.exposeInMainWorld("quickAsk", {
    hide: () => ipcRenderer.send(QUICK_ASK_HIDE_CHANNEL),
    resize: (size: QuickAskResizePayload) =>
      ipcRenderer.send(QUICK_ASK_RESIZE_CHANNEL, size),
    openInApp: () => ipcRenderer.send(QUICK_ASK_OPEN_IN_APP_CHANNEL),
    dragStart: (offset: QuickAskDragStartPayload) =>
      ipcRenderer.send(QUICK_ASK_DRAG_START_CHANNEL, offset),
    dragEnd: () => ipcRenderer.send(QUICK_ASK_DRAG_END_CHANNEL),
    ask: (question: string, conversationId?: string) =>
      ipcRenderer.send(QUICK_ASK_ASK_CHANNEL, question, conversationId),
    cancel: () => ipcRenderer.send(QUICK_ASK_CANCEL_CHANNEL),
    reset: () => ipcRenderer.send(QUICK_ASK_RESET_CHANNEL),
    onEvent: (callback: (event: unknown) => void): (() => void) => {
      const listener = (_e: unknown, event: unknown): void => callback(event);
      ipcRenderer.on(QUICK_ASK_EVENT_CHANNEL, listener);
      return () => ipcRenderer.off(QUICK_ASK_EVENT_CHANNEL, listener);
    },
    onLayout: (callback: (layout: unknown) => void): (() => void) => {
      const listener = (_e: unknown, layout: unknown): void => callback(layout);
      ipcRenderer.on(QUICK_ASK_LAYOUT_CHANNEL, listener);
      return () => ipcRenderer.off(QUICK_ASK_LAYOUT_CHANNEL, listener);
    },
    onShown: (callback: () => void): (() => void) => {
      const listener = (): void => callback();
      ipcRenderer.on(QUICK_ASK_SHOWN_CHANNEL, listener);
      return () => ipcRenderer.off(QUICK_ASK_SHOWN_CHANNEL, listener);
    },
    onShake: (callback: () => void): (() => void) => {
      const listener = (): void => callback();
      ipcRenderer.on(QUICK_ASK_SHAKE_CHANNEL, listener);
      return () => ipcRenderer.off(QUICK_ASK_SHAKE_CHANNEL, listener);
    },
    capture: () => ipcRenderer.send(QUICK_ASK_CAPTURE_CHANNEL),
    discardAttachment: () =>
      ipcRenderer.send(QUICK_ASK_DISCARD_ATTACHMENT_CHANNEL),
    openScreenSettings: () =>
      ipcRenderer.send(QUICK_ASK_SCREEN_SETTINGS_CHANNEL),
    onAttachment: (callback: (payload: unknown) => void): (() => void) => {
      const listener = (_e: unknown, payload: unknown): void =>
        callback(payload);
      ipcRenderer.on(QUICK_ASK_ATTACHMENT_CHANNEL, listener);
      return () => ipcRenderer.off(QUICK_ASK_ATTACHMENT_CHANNEL, listener);
    },
  });
}

function setupQuickAskAnnotatePreload(): void {
  contextBridge.exposeInMainWorld("quickAskAnnotate", {
    shot: (): Promise<string | null> =>
      ipcRenderer.invoke(QUICK_ASK_ANNOTATE_SHOT_CHANNEL),
    done: (dataUrl: string) =>
      ipcRenderer.send(QUICK_ASK_ANNOTATE_DONE_CHANNEL, { dataUrl }),
    cancel: () => ipcRenderer.send(QUICK_ASK_ANNOTATE_DONE_CHANNEL, null),
  });
}

export function setupPreload(argv: string[]): void {
  if (argv.includes(QUICK_ASK_ANNOTATE_WINDOW_ARG)) {
    setupQuickAskAnnotatePreload();
  } else if (argv.includes(QUICK_ASK_WINDOW_ARG)) {
    setupQuickAskPreload();
    // Answer rendering needs the host tRPC bridge for auth tokens and
    // external links.
    process.once("loaded", () => {
      exposeElectronTRPC();
    });
  } else if (argv.includes(APP_WINDOW_ARG)) {
    setupApplicationPreload(argv);
  } else {
    setupArtifactPreviewPreload();
  }
}

setupPreload(process.argv);
