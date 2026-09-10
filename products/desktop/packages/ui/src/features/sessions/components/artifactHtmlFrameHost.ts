import type { ComponentType } from "react";

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
  onOpenExternal: (href: string) => void;
};

export type ArtifactHtmlFrameComponent = ComponentType<ArtifactHtmlFrameProps>;

export const ARTIFACT_HTML_FRAME_COMPONENT = Symbol.for(
  "posthog.ui.ArtifactHtmlFrameComponent",
);
