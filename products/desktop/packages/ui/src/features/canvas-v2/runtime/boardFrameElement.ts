import {
  CANVAS_V2_BOARD_PARTITION,
  CANVAS_V2_BOARD_URL,
  CANVAS_V2_FRAME_NAME,
  CANVAS_V2_FRAME_TO_HOST_CHANNEL,
  CANVAS_V2_HOST_TO_FRAME_CHANNEL,
  type HostToBoardFrameMessage,
} from "@posthog/shared";
import { BOARD_FRAME_TITLE } from "@posthog/ui/features/canvas-v2/canvasV2Copy";

export interface BoardWebviewElement extends HTMLElement {
  send(channel: string, message: unknown): void;
  getWebContentsId(): number;
}

interface WebviewIpcMessageEvent extends Event {
  channel: string;
  args: unknown[];
}

export type BoardFrameElement = HTMLIFrameElement | BoardWebviewElement;

export function isBoardWebview(
  element: BoardFrameElement | null,
): element is BoardWebviewElement {
  return element?.tagName.toLowerCase() === "webview";
}

export function createBoardWebview(): BoardWebviewElement {
  const webview = document.createElement("webview") as BoardWebviewElement;
  webview.setAttribute("partition", CANVAS_V2_BOARD_PARTITION);
  webview.setAttribute("src", CANVAS_V2_BOARD_URL);
  webview.setAttribute("name", CANVAS_V2_FRAME_NAME);
  webview.setAttribute("aria-label", BOARD_FRAME_TITLE);
  webview.className = "absolute inset-0 h-full w-full border-0";
  return webview;
}

export function sendToBoardFrame(
  element: BoardFrameElement | null,
  message: HostToBoardFrameMessage,
): void {
  if (!element) return;
  if (isBoardWebview(element)) {
    element.send(CANVAS_V2_HOST_TO_FRAME_CHANNEL, message);
    return;
  }
  element.contentWindow?.postMessage(message, "*");
}

export function listenToBoardFrame(
  element: BoardFrameElement,
  onMessage: (data: unknown) => void,
): () => void {
  if (!isBoardWebview(element)) {
    const listener = (event: MessageEvent): void => {
      if (event.source !== (element as HTMLIFrameElement).contentWindow) return;
      onMessage(event.data);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }
  const listener = (event: Event): void => {
    const ipc = event as WebviewIpcMessageEvent;
    if (ipc.channel !== CANVAS_V2_FRAME_TO_HOST_CHANNEL) return;
    onMessage(ipc.args[0]);
  };
  element.addEventListener("ipc-message", listener);
  return () => element.removeEventListener("ipc-message", listener);
}
