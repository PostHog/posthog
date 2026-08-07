import { useServiceOptional } from "@posthog/di/react";
import type { ComponentType } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";

export const ARTIFACT_HTML_BRIDGE_MARKER =
  "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

export type ArtifactHtmlFrameRect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

export type ArtifactHtmlFrameProps = {
  document: string;
  fallbackDocument: string;
  name: string;
  messages: readonly Record<string, unknown>[];
  onMessage: (data: unknown, frameRect: ArtifactHtmlFrameRect) => void;
};

export type ArtifactHtmlFrameComponent = ComponentType<ArtifactHtmlFrameProps>;

export const ARTIFACT_HTML_FRAME_COMPONENT = Symbol.for(
  "posthog.ui.ArtifactHtmlFrameComponent",
);

function IframeArtifactHtmlFrame({
  document,
  name,
  messages,
  onMessage,
}: ArtifactHtmlFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const documentUrl = useMemo(
    () => URL.createObjectURL(new Blob([document], { type: "text/html" })),
    [document],
  );

  useEffect(() => () => URL.revokeObjectURL(documentUrl), [documentUrl]);

  const sendMessages = useCallback(() => {
    for (const message of messages) {
      iframeRef.current?.contentWindow?.postMessage(message, "*");
    }
  }, [messages]);

  useEffect(() => {
    sendMessages();
  }, [sendMessages]);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as Record<string, unknown> | null;
      if (
        data?.marker === ARTIFACT_HTML_BRIDGE_MARKER &&
        data.type === "ready"
      ) {
        sendMessages();
      }
      const frameRect = iframeRef.current?.getBoundingClientRect();
      if (!frameRect) return;
      onMessage(event.data, frameRect);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [onMessage, sendMessages]);

  return (
    <iframe
      ref={iframeRef}
      className="size-full border-0 bg-white"
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      src={documentUrl}
      title={`Preview of ${name}`}
      onLoad={sendMessages}
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
