import { useServiceOptional } from "@posthog/di/react";
import {
  type SyntheticEvent,
  useEffect,
  useEffectEvent,
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
  document: htmlDocument,
  name,
  messages,
  onMessage,
  onOpenExternal,
}: ArtifactHtmlFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [documentUrl, setDocumentUrl] = useState<string | null>(null);
  const sendMessages = useEffectEvent(() => {
    for (const message of messages) {
      iframeRef.current?.contentWindow?.postMessage(message, "*");
    }
  });
  const receiveMessage = useEffectEvent(onMessage);
  const openExternal = useEffectEvent(onOpenExternal);

  useEffect(() => {
    const nextDocumentUrl = URL.createObjectURL(
      new Blob([htmlDocument], { type: "text/html" }),
    );
    setDocumentUrl(nextDocumentUrl);
    return () => URL.revokeObjectURL(nextDocumentUrl);
  }, [htmlDocument]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: sendMessages is an Effect Event and must not be a dependency.
  useEffect(() => {
    void messages;
    sendMessages();
  }, [messages]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: callbacks are Effect Events and must not be dependencies.
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as Record<string, unknown> | null;
      if (data?.marker !== ARTIFACT_HTML_BRIDGE_MARKER) return;
      if (data.type === "ready") sendMessages();
      if (data.type === "open-external" && typeof data.href === "string") {
        openExternal(data.href);
        return;
      }
      const frameRect = iframeRef.current?.getBoundingClientRect();
      if (!frameRect) return;
      receiveMessage(data, frameRect);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);

  const handleLoad = (_event: SyntheticEvent<HTMLIFrameElement>) =>
    sendMessages();

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
