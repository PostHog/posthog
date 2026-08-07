import { Button, Text } from "@posthog/quill";
import {
  ARTIFACT_HTML_BRIDGE_MARKER,
  type ArtifactHtmlFrameProps,
} from "@posthog/ui/features/sessions/components/artifactHtmlFrameHost";
import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";
import { ARTIFACT_OPEN_EXTERNAL_CHANNEL } from "../../shared/constants";

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

type RunningArtifactWebviewProps = ArtifactHtmlFrameProps & {
  onStateChange: (state: PreviewState) => void;
};

function RunningArtifactWebview({
  document: htmlDocument,
  name,
  messages,
  onMessage,
  onOpenExternal,
  onStateChange,
}: RunningArtifactWebviewProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const webviewRef = useRef<ArtifactWebviewElement | null>(null);
  const readyRef = useRef(false);
  const messagesRef = useRef(messages);
  const onMessageRef = useRef(onMessage);

  const sendMessages = useCallback(() => {
    if (!readyRef.current) return;
    for (const message of messagesRef.current) {
      webviewRef.current?.send(HOST_TO_ARTIFACT_CHANNEL, message);
    }
  }, []);
  const reportState = useEffectEvent(onStateChange);
  const openExternal = useEffectEvent(onOpenExternal);

  useEffect(() => {
    messagesRef.current = messages;
    sendMessages();
  }, [messages, sendMessages]);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reportState is an Effect Event and must not be a dependency.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) throw new Error("Artifact preview mount is unavailable");

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
      reportState("running");
      sendMessages();
    };
    const onIpcMessage = (event: Event) => {
      const ipcEvent = event as WebviewIpcMessageEvent;
      if (ipcEvent.channel === ARTIFACT_OPEN_EXTERNAL_CHANNEL) {
        const href = ipcEvent.args[0];
        if (typeof href === "string") openExternal(href);
        return;
      }
      if (ipcEvent.channel !== ARTIFACT_TO_HOST_CHANNEL) return;
      const data = ipcEvent.args[0] as Record<string, unknown> | null;
      if (data?.type === "open-external") return;
      if (
        data?.marker === ARTIFACT_HTML_BRIDGE_MARKER &&
        data.type === "ready"
      ) {
        sendMessages();
      }
      onMessageRef.current(data, webview.getBoundingClientRect());
    };
    const onFailed = () => reportState("failed");
    const onGone = () => reportState("failed");
    const onUnresponsive = () => reportState("unresponsive");
    const onResponsive = () => reportState("running");

    webview.addEventListener("dom-ready", onReady);
    webview.addEventListener("ipc-message", onIpcMessage);
    webview.addEventListener("did-fail-load", onFailed);
    webview.addEventListener("render-process-gone", onGone);
    webview.addEventListener("unresponsive", onUnresponsive);
    webview.addEventListener("responsive", onResponsive);
    mount.appendChild(webview);
    webviewRef.current = webview;

    return () => {
      webview.removeEventListener("dom-ready", onReady);
      webview.removeEventListener("ipc-message", onIpcMessage);
      webview.removeEventListener("did-fail-load", onFailed);
      webview.removeEventListener("render-process-gone", onGone);
      webview.removeEventListener("unresponsive", onUnresponsive);
      webview.removeEventListener("responsive", onResponsive);
      readyRef.current = false;
      webviewRef.current = null;
      webview.remove();
    };
  }, [htmlDocument, name, sendMessages]);

  return <div ref={mountRef} className="size-full" />;
}

export function ElectronArtifactHtmlFrame(props: ArtifactHtmlFrameProps) {
  const [state, setState] = useState<PreviewState>("running");
  const active = state === "running" || state === "unresponsive";
  const message =
    state === "failed"
      ? "The preview stopped. Restart it to run the HTML again."
      : state === "unresponsive"
        ? "The preview isn't responding. Stop it or restart it."
        : null;

  return (
    <div className="relative size-full bg-white">
      {active ? (
        <RunningArtifactWebview {...props} onStateChange={setState} />
      ) : null}
      <div className="absolute top-2 right-2 z-50 flex items-center gap-2">
        {message ? (
          <div className="rounded bg-background px-2 py-1 shadow">
            <Text size="xs">{message}</Text>
          </div>
        ) : null}
        {active ? (
          <Button
            size="xs"
            variant="outline"
            onClick={() => setState("stopped")}
          >
            Stop preview
          </Button>
        ) : (
          <Button
            size="xs"
            variant="outline"
            onClick={() => setState("running")}
          >
            Restart preview
          </Button>
        )}
      </div>
    </div>
  );
}
