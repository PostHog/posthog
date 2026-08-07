import { useServiceOptional } from "@posthog/di/react";
import {
  type SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ARTIFACT_HTML_BRIDGE_MARKER,
  ARTIFACT_HTML_FRAME_COMPONENT,
  type ArtifactHtmlFrameComponent,
  type ArtifactHtmlFrameProps,
} from "./artifactHtmlFrameHost";

function IframeArtifactHtmlFrame({
  document,
  name,
  messages,
  onMessage,
  onOpenExternal,
}: ArtifactHtmlFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const onMessageRef = useRef(onMessage);
  const onOpenExternalRef = useRef(onOpenExternal);
  const [documentUrl, setDocumentUrl] = useState<string | null>(null);

  useEffect(() => {
    const nextDocumentUrl = URL.createObjectURL(
      new Blob([document], { type: "text/html" }),
    );
    setDocumentUrl(nextDocumentUrl);
    return () => URL.revokeObjectURL(nextDocumentUrl);
  }, [document]);

  const sendMessages = useCallback(() => {
    for (const message of messages) {
      iframeRef.current?.contentWindow?.postMessage(message, "*");
    }
  }, [messages]);
  const sendMessagesRef = useRef(sendMessages);

  useEffect(() => {
    sendMessagesRef.current = sendMessages;
    sendMessages();
  }, [sendMessages]);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onOpenExternalRef.current = onOpenExternal;
  }, [onMessage, onOpenExternal]);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as Record<string, unknown> | null;
      if (
        data?.marker === ARTIFACT_HTML_BRIDGE_MARKER &&
        data.type === "ready"
      ) {
        sendMessagesRef.current();
      }
      if (data?.type === "open-external" && typeof data.href === "string") {
        onOpenExternalRef.current(data.href);
        return;
      }
      const frameRect = iframeRef.current?.getBoundingClientRect();
      if (!frameRect) return;
      onMessageRef.current(event.data, frameRect);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);

  const handleLoad = (_event: SyntheticEvent<HTMLIFrameElement>) =>
    sendMessagesRef.current();

  return (
    <iframe
      ref={iframeRef}
      className="size-full border-0 bg-white"
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      src={documentUrl ?? "about:blank"}
      title={`Preview of ${name}`}
      onLoad={handleLoad}
    />
  );
}

export function ArtifactHtmlFrame(props: ArtifactHtmlFrameProps) {
  const HostFrame = useServiceOptional<ArtifactHtmlFrameComponent>(
    ARTIFACT_HTML_FRAME_COMPONENT,
  );
  return HostFrame ? (
    <HostFrame {...props} />
  ) : (
    <IframeArtifactHtmlFrame {...props} document={props.fallbackDocument} />
  );
}
