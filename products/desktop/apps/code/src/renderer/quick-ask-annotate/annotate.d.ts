/** Bridge exposed by the annotator preload branch (see src/main/preload.ts). */
interface QuickAskAnnotateBridge {
  /** The frozen screen as a PNG data URL; null when capture was lost. */
  shot: () => Promise<string | null>;
  done: (dataUrl: string) => void;
  cancel: () => void;
}

interface Window {
  quickAskAnnotate: QuickAskAnnotateBridge;
}
