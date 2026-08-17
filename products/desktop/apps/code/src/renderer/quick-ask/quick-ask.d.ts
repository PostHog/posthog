/** Geometry pushed by the main process after every layout change. */
interface QuickAskLayout {
  /** Card renders above the pill (summoned near the bottom of the screen). */
  flip: boolean;
  /** Max allowed answer-card height in CSS pixels. */
  cardMax: number;
}

/** Bridge exposed by the quick-ask preload branch (see src/main/preload.ts). */
interface QuickAskBridge {
  hide: () => void;
  resize: (height: number) => void;
  openInApp: () => void;
  setInteractive: (interactive: boolean) => void;
  /** Native app-region dragging fights click-through; the panel drags itself. */
  dragStart: (offset: { dx: number; dy: number }) => void;
  dragEnd: () => void;
  ask: (question: string, conversationId?: string) => void;
  cancel: () => void;
  /** Events are `QuickAskEvent`s from @posthog/core/quick-ask/quick-ask. */
  onEvent: (callback: (event: unknown) => void) => () => void;
  onLayout: (callback: (layout: QuickAskLayout) => void) => () => void;
  onShown: (callback: () => void) => () => void;
}

interface Window {
  quickAsk?: QuickAskBridge;
}
