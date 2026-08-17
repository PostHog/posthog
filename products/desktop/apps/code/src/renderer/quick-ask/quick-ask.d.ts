/** Bridge exposed by the quick-ask preload branch (see src/main/preload.ts). */
interface QuickAskBridge {
  hide: () => void;
  resize: (height: number) => void;
  openInApp: () => void;
  setInteractive: (interactive: boolean) => void;
  onShown: (callback: () => void) => () => void;
}

interface Window {
  quickAsk?: QuickAskBridge;
}
