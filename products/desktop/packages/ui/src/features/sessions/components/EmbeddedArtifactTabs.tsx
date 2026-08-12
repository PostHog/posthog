import { X } from "@phosphor-icons/react";
import {
  DEFAULT_PANEL_IDS,
  DEFAULT_TAB_IDS,
} from "@posthog/core/panels/panelConstants";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { getLeafPanel } from "@posthog/ui/features/panels/panelStoreHelpers";
import { type ReactNode, useEffect } from "react";
import { ArtifactPreview } from "./ArtifactPreview";

// Shows the task's own artifact tabs around a session embedded outside the task
// route — the command center grid, the canvas side panel — where the panel tab
// strip that renders them isn't mounted. Same tabs, same store: a file opened
// here is the tab the task view shows, and the other way round.
export function EmbeddedArtifactTabs({
  taskId,
  children,
}: {
  taskId: string;
  children: ReactNode;
}) {
  const layout = usePanelLayoutStore((state) => state.taskLayouts[taskId]);
  const initializeTask = usePanelLayoutStore((state) => state.initializeTask);
  const setActiveTab = usePanelLayoutStore((state) => state.setActiveTab);
  const closeTab = usePanelLayoutStore((state) => state.closeTab);

  // Opening a tab needs a layout to write into, and a task the user never
  // opened has none yet.
  useEffect(() => {
    if (!layout) initializeTask(taskId);
  }, [layout, initializeTask, taskId]);

  const panel = layout
    ? getLeafPanel(layout.panelTree, DEFAULT_PANEL_IDS.MAIN_PANEL)
    : null;
  // Artifacts only: a file or context tab belongs to the task's editor panels,
  // which this surface has no room for.
  const artifactTabs =
    panel?.content.tabs.filter((tab) => tab.data.type === "artifact") ?? [];
  const activeTab =
    artifactTabs.find((tab) => tab.id === panel?.content.activeTabId) ?? null;
  const activeArtifact =
    activeTab?.data.type === "artifact" ? activeTab.data : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {panel && artifactTabs.length > 0 && (
        <div className="flex shrink-0 items-center gap-1 overflow-hidden border-gray-6 border-b px-1 py-1">
          <TabPill
            label="Chat"
            active={!activeTab}
            onSelect={() =>
              setActiveTab(taskId, panel.id, DEFAULT_TAB_IDS.LOGS)
            }
          />
          {artifactTabs.map((tab) => (
            <TabPill
              key={tab.id}
              label={tab.label}
              active={tab.id === activeTab?.id}
              onSelect={() => setActiveTab(taskId, panel.id, tab.id)}
              onClose={() => closeTab(taskId, panel.id, tab.id)}
            />
          ))}
        </div>
      )}
      {/* An artifact covers the session rather than replacing it, so the thread
          keeps its box and its virtualized rows their measurements. */}
      <div className="relative flex min-h-0 flex-1 flex-col">
        {children}
        {activeArtifact && activeTab && (
          <div className="absolute inset-0 flex flex-col bg-background">
            <ArtifactPreview
              taskId={taskId}
              runId={activeArtifact.runId}
              artifactId={activeArtifact.artifactId}
              name={activeTab.label}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// A plain button rather than a quill TabsTrigger: the close affordance would
// nest a button inside it.
function TabPill({
  label,
  active,
  onSelect,
  onClose,
}: {
  label: string;
  active: boolean;
  onSelect: () => void;
  onClose?: () => void;
}) {
  return (
    <div className="flex min-w-0 items-center">
      <button
        type="button"
        onClick={onSelect}
        title={label}
        className={`max-w-[160px] truncate rounded px-1.5 py-0.5 text-[12px] transition-colors ${
          active ? "bg-gray-4 text-gray-12" : "text-gray-10 hover:bg-gray-3"
        }`}
      >
        {label}
      </button>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${label}`}
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
        >
          <X size={10} />
        </button>
      )}
    </div>
  );
}
