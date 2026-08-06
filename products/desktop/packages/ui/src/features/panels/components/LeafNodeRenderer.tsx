import { Cloud as CloudIcon } from "@phosphor-icons/react";
import { shouldShowTabBar } from "@posthog/core/panels/panelStoreHelpers";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import type React from "react";
import { useMemo } from "react";
import { useIsWorkspaceCloudRun } from "../../workspace/useWorkspace";
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
  onSplitPanel: (panelId: string, direction: SplitDirection) => void;
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
  onSplitPanel,
}) => {
  const isCloud = useIsWorkspaceCloudRun(taskId);
  const tabs = useTabInjection(
    node.content.tabs,
    node.id,
    taskId,
    task,
    closeTab,
  );
  const activeTabId = tabs.some((t) => t.id === node.content.activeTabId)
    ? node.content.activeTabId
    : (tabs[0]?.id ?? node.content.activeTabId);

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

  const showTabs = node.content.showTabs !== false && shouldShowTabBar(tabs);

  const contentWithComponents = {
    ...node.content,
    tabs,
    activeTabId,
    showTabs,
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
      onSplitPanel={
        isCloud ? undefined : (direction) => onSplitPanel(node.id, direction)
      }
      emptyState={cloudEmptyState}
    />
  );
};
