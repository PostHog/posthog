/**
 * The contract between the annotator and whatever hosts it. The Electron
 * host implements it in its preload (window.quickAskAnnotate).
 */
export interface QuickAskAnnotateHostBridge {
  /** The frozen screen as a PNG data URL; null when capture was lost. */
  shot: () => Promise<string | null>;
  done: (dataUrl: string) => void;
  cancel: () => void;
}

export function annotateHost(): QuickAskAnnotateHostBridge {
  return (window as unknown as { quickAskAnnotate: QuickAskAnnotateHostBridge })
    .quickAskAnnotate;
}
