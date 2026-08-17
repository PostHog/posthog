/** Bridge exposed by the quick-ask preload branch (see src/main/preload.ts). */
interface QuickAskBridge {
  hide: () => void;
  resize: (height: number) => void;
  openInApp: () => void;
  setInteractive: (interactive: boolean) => void;
  ask: (question: string, conversationId?: string) => void;
  cancel: () => void;
  /** Events are `QuickAskEvent`s from @posthog/core/quick-ask/quick-ask. */
  onEvent: (callback: (event: unknown) => void) => () => void;
  onShown: (callback: () => void) => () => void;
}

interface Window {
  quickAsk?: QuickAskBridge;
}
