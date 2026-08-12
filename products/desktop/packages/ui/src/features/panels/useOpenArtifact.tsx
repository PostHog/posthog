import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useRevealPanels } from "@posthog/ui/features/panels/useRevealPanels";
import { createContext, type ReactNode, useCallback, useContext } from "react";

export interface ArtifactTarget {
  runId: string;
  artifactId: string;
  name: string;
}

// A surface that shows the session without the task's panels — the command
// center grid, the canvas side panel — hosts artifact tabs itself, so a file
// opens where the user is looking instead of on another route.
const ArtifactTabHostContext = createContext<
  ((artifact: ArtifactTarget) => void) | null
>(null);

export function ArtifactTabHostProvider({
  open,
  children,
}: {
  open: (artifact: ArtifactTarget) => void;
  children: ReactNode;
}) {
  return (
    <ArtifactTabHostContext.Provider value={open}>
      {children}
    </ArtifactTabHostContext.Provider>
  );
}

/** Opens an artifact as a tab: in the surrounding host, else in the task's panels. */
export function useOpenArtifact(): (
  taskId: string,
  artifact: ArtifactTarget,
) => void {
  const host = useContext(ArtifactTabHostContext);
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const revealPanels = useRevealPanels();

  return useCallback(
    (taskId, artifact) => {
      if (host) {
        host(artifact);
        return;
      }
      openArtifactTab(taskId, artifact);
      revealPanels();
    },
    [host, openArtifactTab, revealPanels],
  );
}
