import { Cloud as CloudIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import type React from "react";
import { useEffect, useMemo } from "react";
import { useHostCapabilities } from "../../../shell/useHostCapabilities";
import { useIsCloudTask } from "../../workspace/useWorkspace";
import { useTabInjection } from "../hooks/usePanelLayoutHooks";
import type { SplitDirection } from "../panelLayoutStore";
import type { LeafPanel } from "../panelTypes";
import { TabbedPanel } from "./TabbedPanel";

interface LeafNodeRendererProps {
  node: LeafPanel;
  taskId: string;
  task: Task;
  closeTab: (taskId: string, panelId: string, tabId: string) => void;
  closeOtherTabs: (panelId: string, tabId: string) => void;
  closeTabsToRight: (panelId: string, tabId: string) => void;
  keepTab: (panelId: string, tabId: string) => void;
  draggingTabId: string | null;
  draggingTabPanelId: string | null;
  onActiveTabChange: (panelId: string, tabId: string) => void;
  onPanelFocus: (panelId: string) => void;
  onAddTerminal: (panelId: string) => void;
  onSplitPanel: (panelId: string, direction: SplitDirection) => void;
  onClosePanel: (panelId: string) => void;
}

export const LeafNodeRenderer: React.FC<LeafNodeRendererProps> = ({
  node,
  taskId,
  task,
  closeTab,
  closeOtherTabs,
  closeTabsToRight,
  keepTab,
  draggingTabId,
  draggingTabPanelId,
  onActiveTabChange,
  onPanelFocus,
  onAddTerminal,
  onSplitPanel,
  onClosePanel,
}) => {
  const isCloud = useIsCloudTask(task);
  const { localWorkspaces } = useHostCapabilities();
  // Hide the terminal for cloud runs, and on cloud-only hosts (web).
  const hideTerminal = isCloud || !localWorkspaces;
  const inputTabs = useMemo(
    () =>
      hideTerminal
        ? node.content.tabs.filter((t) => t.data.type !== "terminal")
        : node.content.tabs,
    [node.content.tabs, hideTerminal],
  );
  const tabs = useTabInjection(inputTabs, node.id, taskId, task, closeTab);
  const activeTabId = tabs.some((t) => t.id === node.content.activeTabId)
    ? node.content.activeTabId
    : (tabs[0]?.id ?? node.content.activeTabId);
  // Keyboard actions read the stored active tab, so point it at the rendered
  // one when the stored tab is a hidden terminal.
  useEffect(() => {
    if (activeTabId && activeTabId !== node.content.activeTabId) {
      onActiveTabChange(node.id, activeTabId);
    }
  }, [activeTabId, node.content.activeTabId, node.id, onActiveTabChange]);
  // A pane whose only tabs are hidden shows nothing; the close button lets
  // the user collapse it.
  const hasOnlyHiddenTabs = tabs.length === 0 && node.content.tabs.length > 0;

  const cloudEmptyState = useMemo(
    () =>
      isCloud ? (
        <Empty className="h-full border-0 bg-(--gray-2)">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CloudIcon size={24} className="text-gray-10" />
            </EmptyMedia>
            <EmptyTitle>Cloud runs are read-only</EmptyTitle>
            <EmptyDescription>
              Local workspace tools are unavailable for this run.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : undefined,
    [isCloud],
  );

  const contentWithComponents = {
    ...node.content,
    tabs,
    activeTabId,
  };

  return (
    <TabbedPanel
      panelId={node.id}
      mountScopeKey={taskId}
      content={contentWithComponents}
      onActiveTabChange={onActiveTabChange}
      onCloseOtherTabs={closeOtherTabs}
      onCloseTabsToRight={closeTabsToRight}
      onKeepTab={keepTab}
      onPanelFocus={onPanelFocus}
      draggingTabId={draggingTabId}
      draggingTabPanelId={draggingTabPanelId}
      allowPanelSplit={!isCloud}
      onAddTerminal={hideTerminal ? undefined : () => onAddTerminal(node.id)}
      onSplitPanel={
        isCloud ? undefined : (direction) => onSplitPanel(node.id, direction)
      }
      onClosePanel={hasOnlyHiddenTabs ? () => onClosePanel(node.id) : undefined}
      emptyState={cloudEmptyState}
    />
  );
};
