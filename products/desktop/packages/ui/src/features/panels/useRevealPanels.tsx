import { createContext, type ReactNode, useContext } from "react";

// Opening a file, artifact or context tab only writes into panelLayoutStore —
// the tab strip that renders it is mounted by the task detail route alone.
// Surfaces that embed a session without it (the command center grid, the canvas
// side panel) provide a callback that brings the panels on screen, so a click
// lands somewhere visible instead of silently mutating the stored layout.
const RevealPanelsContext = createContext<(() => void) | null>(null);

export function RevealPanelsProvider({
  reveal,
  children,
}: {
  reveal: () => void;
  children: ReactNode;
}) {
  return (
    <RevealPanelsContext.Provider value={reveal}>
      {children}
    </RevealPanelsContext.Provider>
  );
}

const noop = (): void => {};

/** Call after opening a tab. No-op where the panels are already on screen. */
export function useRevealPanels(): () => void {
  return useContext(RevealPanelsContext) ?? noop;
}
