import type { ComponentType } from "react";

export type ClassicFrameStatus = "loading" | "ready" | "error";

export interface ClassicFrameProps {
  url: string;
  accountId: string;
  onStatusChange: (status: ClassicFrameStatus) => void;
}

export type ClassicFrameComponent = ComponentType<ClassicFrameProps>;

export const CLASSIC_FRAME_COMPONENT = Symbol.for(
  "posthog.ui.ClassicFrameComponent",
);
