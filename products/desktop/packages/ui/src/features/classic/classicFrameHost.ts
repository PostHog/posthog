import type { ComponentType } from "react";

export type ClassicFrameStatus = "loading" | "ready" | "error";

export interface ClassicFrameProps {
  url: string;
  accountId: string;
  onStatusChange: (status: ClassicFrameStatus, detail?: string) => void;
}

export type ClassicFrameComponent = ComponentType<ClassicFrameProps> & {
  supportsUrl?: (url: string) => boolean;
};

export const CLASSIC_FRAME_COMPONENT = Symbol.for(
  "posthog.ui.ClassicFrameComponent",
);
