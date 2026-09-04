export interface CanvasBoardFrameDocument {
  readonly html: string;
  readonly csp: string;
}

export interface CanvasBoardFrameHost {
  registerDocument(document: CanvasBoardFrameDocument): void;
}

export const CANVAS_BOARD_FRAME_HOST = Symbol.for(
  "posthog.platform.canvasBoardFrameHost",
);
