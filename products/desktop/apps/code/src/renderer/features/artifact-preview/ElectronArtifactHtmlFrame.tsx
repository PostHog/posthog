import { Button, Text } from "@posthog/quill";
import {
  ARTIFACT_HTML_BRIDGE_MARKER,
  type ArtifactHtmlFrameProps,
} from "@posthog/ui/features/sessions/components/artifactHtmlFrame";
import { useCallback, useEffect, useRef, useState } from "react";

const HOST_TO_ARTIFACT_CHANNEL = "posthog-artifact-host-message";
const ARTIFACT_TO_HOST_CHANNEL = "posthog-artifact-message";
const DATA_URL_PREFIX = "data:text/html;charset=utf-8,";

type ArtifactWebviewElement = HTMLElement & {
  send: (channel: string, ...args: unknown[]) => void;
};

type WebviewIpcMessageEvent = Event & {
  channel: string;
  args: unknown[];
};

type PreviewState = "running" | "stopped" | "failed" | "unresponsive";

export function ElectronArtifactHtmlFrame({
  document: htmlDocument,
  name,
  messages,
  onMessage,
}: ArtifactHtmlFrameProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const webviewRef = useRef<ArtifactWebviewElement | null>(null);
  const readyRef = useRef(false);
  const onMessageRef = useRef(onMessage);
  const [state, setState] = useState<PreviewState>("running");
  onMessageRef.current = onMessage;
  const active = state === "running" || state === "unresponsive";

  const sendMessages = useCallback(() => {
    if (!readyRef.current) return;
    for (const message of messages) {
      webviewRef.current?.send(HOST_TO_ARTIFACT_CHANNEL, message);
    }
  }, [messages]);
  const sendMessagesRef = useRef(sendMessages);
  sendMessagesRef.current = sendMessages;

  useEffect(() => {
    if (!active) return;
    const mount = mountRef.current;
    if (!mount) return;

    const webview = document.createElement("webview") as ArtifactWebviewElement;
    const partition = `artifact-preview-${crypto.randomUUID()}`;
    webview.className = "size-full";
    webview.setAttribute("partition", partition);
    webview.setAttribute(
      "src",
      `${DATA_URL_PREFIX}${encodeURIComponent(htmlDocument)}`,
    );
    webview.setAttribute("aria-label", `Preview of ${name}`);

    const onReady = () => {
      readyRef.current = true;
      setState("running");
      sendMessagesRef.current();
    };
    const onIpcMessage = (event: Event) => {
      const ipcEvent = event as WebviewIpcMessageEvent;
      if (ipcEvent.channel !== ARTIFACT_TO_HOST_CHANNEL) return;
      const data = ipcEvent.args[0] as Record<string, unknown> | null;
      if (
        data?.marker === ARTIFACT_HTML_BRIDGE_MARKER &&
        data.type === "ready"
      ) {
        sendMessagesRef.current();
      }
      onMessageRef.current(data, webview.getBoundingClientRect());
    };
    const onFailed = () => setState("failed");
    const onGone = () => setState("failed");
    const onUnresponsive = () => setState("unresponsive");
    const onResponsive = () => setState("running");

    webview.addEventListener("dom-ready", onReady);
    webview.addEventListener("ipc-message", onIpcMessage);
    webview.addEventListener("did-fail-load", onFailed);
    webview.addEventListener("render-process-gone", onGone);
    webview.addEventListener("unresponsive", onUnresponsive);
    webview.addEventListener("responsive", onResponsive);
    mount.appendChild(webview);
    webviewRef.current = webview;

    return () => {
      readyRef.current = false;
      webviewRef.current = null;
      webview.remove();
    };
  }, [active, htmlDocument, name]);

  useEffect(() => {
    sendMessages();
  }, [sendMessages]);

  const stop = () => setState("stopped");
  const restart = () => setState("running");

  const message =
    state === "failed"
      ? "The preview stopped. Restart it to run the HTML again."
      : state === "unresponsive"
        ? "The preview isn't responding. Stop it or restart it."
        : null;

  return (
    <div className="relative size-full bg-white">
      <div ref={mountRef} className="size-full" />
      <div className="absolute top-2 right-2 z-50 flex items-center gap-2">
        {message ? (
          <div className="rounded bg-background px-2 py-1 shadow">
            <Text size="xs">{message}</Text>
          </div>
        ) : null}
        {state === "stopped" || state === "failed" ? (
          <Button size="xs" variant="outline" onClick={restart}>
            Restart preview
          </Button>
        ) : (
          <Button size="xs" variant="outline" onClick={stop}>
            Stop preview
          </Button>
        )}
      </div>
    </div>
  );
}
