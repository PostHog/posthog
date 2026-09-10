export interface SketchpadFrameDocument {
  readonly html: string;
  readonly csp: string;
}

export interface SketchpadFrameHost {
  registerDocument(document: SketchpadFrameDocument): void;
}

export const SKETCHPAD_FRAME_HOST = Symbol.for(
  "posthog.platform.sketchpadFrameHost",
);
