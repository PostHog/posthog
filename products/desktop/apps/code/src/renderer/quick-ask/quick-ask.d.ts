/** Geometry pushed by the main process after every layout change. */
interface QuickAskLayout {
  /** Card renders above the pill (summoned near the bottom of the screen). */
  flip: boolean;
  /** Max window height: pill anchor to screen edge, in CSS pixels. */
  maxHeight: number;
}

/** Bridge exposed by the quick-ask preload branch (see src/main/preload.ts). */
interface QuickAskBridge {
  hide: () => void;
  /** Reports the content's bounding box; the window's bounds hug it. */
  resize: (size: { width: number; height: number }) => void;
  openInApp: () => void;
  /** Native app-region dragging fights click-through; the panel drags itself. */
  dragStart: (offset: { dx: number; dy: number }) => void;
  dragEnd: () => void;
  ask: (question: string, conversationId?: string) => void;
  cancel: () => void;
  /** Drops the thread and pre-warms the next one. */
  reset: () => void;
  /** Events are `QuickAskEvent`s from @posthog/core/quick-ask/quick-ask. */
  onEvent: (callback: (event: unknown) => void) => () => void;
  onLayout: (callback: (layout: QuickAskLayout) => void) => () => void;
  onShown: (callback: () => void) => () => void;
  /** Fired when the panel is shaken while dragged. */
  onShake: (callback: () => void) => () => void;
  /** Hides the panel, freezes the screen, and opens the annotator. */
  capture: () => void;
  discardAttachment: () => void;
  /** Opens the OS pane that grants screen-recording permission. */
  openScreenSettings: () => void;
  /** Payloads are `QuickAskAttachmentPayload`s from shared/constants. */
  onAttachment: (callback: (payload: unknown) => void) => () => void;
}

interface Window {
  quickAsk?: QuickAskBridge;
}
