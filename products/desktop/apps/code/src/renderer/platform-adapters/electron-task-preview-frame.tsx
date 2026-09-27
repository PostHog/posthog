import { screenshotArea } from "@posthog/shared";
import type {
  TaskPreviewFrameProps,
  TaskPreviewPin,
  TaskPreviewRect,
} from "@posthog/ui/features/task-preview/taskPreviewFrameHost";
import { useEffect, useRef } from "react";
import {
  HOST_TO_TASK_PREVIEW_CHANNEL,
  TASK_BROWSER_PARTITION,
  TASK_PREVIEW_PARTITION,
  TASK_PREVIEW_TO_HOST_CHANNEL,
} from "../../shared/constants";
import {
  sanitizeTaskPreviewGuestMessage,
  type TaskPreviewHostMessage,
} from "../../shared/task-preview-message";
import { trpcClient } from "../trpc/client";

type CapturedImage = {
  isEmpty: () => boolean;
  toDataURL: () => string;
};

type TaskPreviewWebviewElement = HTMLElement & {
  send: (channel: string, ...args: unknown[]) => void;
  getURL: () => string;
  getTitle: () => string;
  loadURL: (url: string) => Promise<void>;
  canGoBack: () => boolean;
  canGoForward: () => boolean;
  goBack: () => void;
  goForward: () => void;
  getWebContentsId: () => number;
  capturePage: (rect?: {
    x: number;
    y: number;
    width: number;
    height: number;
  }) => Promise<CapturedImage>;
};

type WebviewLoadFailureEvent = Event & {
  errorCode?: number;
  isMainFrame?: boolean;
};

type WebviewIpcMessageEvent = Event & {
  channel: string;
  args: unknown[];
};

const ABORTED_LOAD_ERROR_CODE = -3;
const LOCATE_RETRY_WINDOW_MS = 10_000;

function locationPath(url: string, session: "sandbox" | "browser"): string {
  try {
    const parsed = new URL(url);
    return session === "browser"
      ? parsed.toString()
      : `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return session === "browser" ? url : "/";
  }
}

async function captureAround(
  webview: TaskPreviewWebviewElement,
  rect: TaskPreviewRect,
): Promise<string | null> {
  const area = screenshotArea(rect, {
    width: webview.clientWidth,
    height: webview.clientHeight,
  });
  if (!area) return null;
  try {
    const image = await webview.capturePage(area);
    return image.isEmpty() ? null : image.toDataURL();
  } catch {
    return null;
  }
}

export function ElectronTaskPreviewFrame({
  url,
  taskId,
  frameId,
  session,
  title,
  picking,
  pins,
  locateRequest,
  onLoadFailed,
  onPicked,
  onPickCancelled,
  onActivatePin,
  onPinsChanged,
  navigationRequest,
  onLocationChange,
  tracking,
  onTrackedRect,
}: TaskPreviewFrameProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const webviewRef = useRef<TaskPreviewWebviewElement | null>(null);
  const readyRef = useRef(false);
  const lastLocateRef = useRef<{ id: string; at: number } | null>(null);
  const stateRef = useRef<{ picking: boolean; pins: TaskPreviewPin[] }>({
    picking,
    pins,
  });
  const callbacksRef = useRef({
    onLoadFailed,
    onPicked,
    onPickCancelled,
    onActivatePin,
    onPinsChanged,
    onLocationChange,
    onTrackedRect,
  });

  useEffect(() => {
    callbacksRef.current = {
      onLoadFailed,
      onPicked,
      onPickCancelled,
      onActivatePin,
      onPinsChanged,
      onLocationChange,
      onTrackedRect,
    };
  }, [
    onTrackedRect,
    onLoadFailed,
    onPicked,
    onPickCancelled,
    onActivatePin,
    onPinsChanged,
    onLocationChange,
  ]);

  const send = (message: TaskPreviewHostMessage) => {
    if (readyRef.current) {
      webviewRef.current?.send(HOST_TO_TASK_PREVIEW_CHANNEL, message);
    }
  };
  const sendRef = useRef(send);
  sendRef.current = send;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const webview = document.createElement(
      "webview",
    ) as TaskPreviewWebviewElement;
    webview.className = "size-full";
    webview.setAttribute("allowpopups", "");
    webview.setAttribute(
      "partition",
      session === "browser" ? TASK_BROWSER_PARTITION : TASK_PREVIEW_PARTITION,
    );
    let cancelled = false;
    let registeredId: number | null = null;

    const onReady = () => {
      readyRef.current = true;
      const webContentsId = webview.getWebContentsId();
      if (registeredId !== webContentsId) {
        registeredId = webContentsId;
        void trpcClient.taskBrowser.register
          .mutate({
            browserId: frameId,
            taskId,
            webContentsId,
            kind: session === "browser" ? "browser" : "preview",
          })
          .catch(() => undefined);
      }
      sendRef.current({ type: "pins", items: stateRef.current.pins });
      sendRef.current({ type: "pick", active: stateRef.current.picking });
      const locate = lastLocateRef.current;
      if (locate && Date.now() - locate.at < LOCATE_RETRY_WINDOW_MS) {
        sendRef.current({ type: "locate", id: locate.id });
      }
    };
    const onFailed = (event: Event) => {
      const failure = event as WebviewLoadFailureEvent;
      if (
        failure.isMainFrame === false ||
        failure.errorCode === ABORTED_LOAD_ERROR_CODE
      ) {
        return;
      }
      callbacksRef.current.onLoadFailed();
    };
    const onGone = () => callbacksRef.current.onLoadFailed();
    const reportLocation = () =>
      callbacksRef.current.onLocationChange({
        path: locationPath(webview.getURL(), session),
        canGoBack: webview.canGoBack(),
        canGoForward: webview.canGoForward(),
        title: webview.getTitle(),
      });
    const onNavigated = (event: Event) => {
      if ((event as Event & { isMainFrame?: boolean }).isMainFrame === false) {
        return;
      }
      reportLocation();
    };
    const onIpcMessage = (event: Event) => {
      const ipcEvent = event as WebviewIpcMessageEvent;
      if (ipcEvent.channel !== TASK_PREVIEW_TO_HOST_CHANNEL) return;
      const message = sanitizeTaskPreviewGuestMessage(ipcEvent.args[0]);
      if (!message) return;
      if (message.type === "picked") {
        void captureAround(webview, message.rect).then((screenshot) => {
          sendRef.current({ type: "release" });
          callbacksRef.current.onPicked(
            message.element,
            message.rect,
            screenshot,
          );
        });
      } else if (message.type === "pick-cancelled") {
        callbacksRef.current.onPickCancelled();
      } else if (message.type === "tracked-rect") {
        callbacksRef.current.onTrackedRect(message.rect);
      } else if (message.type === "pins-changed") {
        callbacksRef.current.onPinsChanged(message.ids);
      } else {
        callbacksRef.current.onActivatePin(message.id);
      }
    };

    webview.addEventListener("dom-ready", onReady);
    webview.addEventListener("did-fail-load", onFailed);
    webview.addEventListener("render-process-gone", onGone);
    webview.addEventListener("ipc-message", onIpcMessage);
    webview.addEventListener("did-navigate", onNavigated);
    webview.addEventListener("did-navigate-in-page", onNavigated);
    webview.addEventListener("page-title-updated", reportLocation);
    const authorize =
      session === "browser"
        ? Promise.resolve(url)
        : trpcClient.taskPreview.authorize.mutate({ url }).catch(() => null);
    void authorize.then((authorizedUrl) => {
      if (cancelled) return;
      if (!authorizedUrl) {
        callbacksRef.current.onLoadFailed();
        return;
      }
      webview.setAttribute("src", authorizedUrl);
      mount.appendChild(webview);
      webviewRef.current = webview;
    });

    return () => {
      cancelled = true;
      if (registeredId !== null) {
        void trpcClient.taskBrowser.unregister
          .mutate({ browserId: frameId, webContentsId: registeredId })
          .catch(() => undefined);
      }
      webview.removeEventListener("dom-ready", onReady);
      webview.removeEventListener("did-fail-load", onFailed);
      webview.removeEventListener("render-process-gone", onGone);
      webview.removeEventListener("ipc-message", onIpcMessage);
      webview.removeEventListener("did-navigate", onNavigated);
      webview.removeEventListener("did-navigate-in-page", onNavigated);
      webview.removeEventListener("page-title-updated", reportLocation);
      readyRef.current = false;
      webviewRef.current = null;
      webview.remove();
    };
  }, [url, session, frameId, taskId]);

  useEffect(() => {
    stateRef.current.pins = pins;
    sendRef.current({ type: "pins", items: pins });
  }, [pins]);

  useEffect(() => {
    stateRef.current.picking = picking;
    sendRef.current({ type: "pick", active: picking });
  }, [picking]);

  useEffect(() => {
    if (locateRequest) {
      lastLocateRef.current = { id: locateRequest.id, at: Date.now() };
      sendRef.current({ type: "locate", id: locateRequest.id });
    }
  }, [locateRequest]);

  useEffect(() => {
    if (!tracking) sendRef.current({ type: "untrack" });
  }, [tracking]);

  useEffect(() => {
    const webview = webviewRef.current;
    if (!navigationRequest || !webview || !readyRef.current) return;
    if (navigationRequest.kind === "back") {
      if (webview.canGoBack()) webview.goBack();
      return;
    }
    if (navigationRequest.kind === "forward") {
      if (webview.canGoForward()) webview.goForward();
      return;
    }
    const current = new URL(webview.getURL());
    const next = new URL(navigationRequest.path, current.origin);
    const allowed =
      session === "browser"
        ? next.protocol === "http:" || next.protocol === "https:"
        : next.origin === current.origin;
    if (allowed) {
      void webview.loadURL(next.toString()).catch(() => undefined);
    }
  }, [navigationRequest, session]);

  useEffect(() => {
    webviewRef.current?.setAttribute("aria-label", title);
  }, [title]);

  return <div ref={mountRef} className="size-full bg-[white]" />;
}
