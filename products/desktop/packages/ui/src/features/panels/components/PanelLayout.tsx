import { DragDropProvider } from "@dnd-kit/react";
import type { Task } from "@posthog/shared/domain-types";
import type React from "react";
import { useCallback, useEffect } from "react";
import { useDragDropHandlers } from "../hooks/useDragDropHandlers";
import { usePanelKeyboardShortcuts } from "../hooks/usePanelKeyboardShortcuts";
import {
  usePanelGroupRefs,
  usePanelLayoutState,
  usePanelSizeSync,
} from "../hooks/usePanelLayoutHooks";
import type { SplitDirection } from "../panelLayoutStore";
import { usePanelLayoutStore } from "../panelLayoutStore";
import type { PanelNode } from "../panelTypes";
import { GroupNodeRenderer } from "./GroupNodeRenderer";
import { LeafNodeRenderer } from "./LeafNodeRenderer";

interface PanelLayoutProps {
  taskId: string;
  task: Task;
}

const PanelLayoutRenderer: React.FC<{
  node: PanelNode;
  taskId: string;
  task: Task;
}> = ({ node, taskId, task }) => {
  const layoutState = usePanelLayoutState(taskId);
  const { groupRefs, setGroupRef } = usePanelGroupRefs();

  usePanelSizeSync(node, groupRefs.current);

  const handleSetActiveTab = useCallback(
    (panelId: string, tabId: string) => {
      layoutState.setActiveTab(taskId, panelId, tabId);
    },
    [layoutState, taskId],
  );

  const handleCloseOtherTabs = useCallback(
    (panelId: string, tabId: string) => {
      layoutState.closeOtherTabs(taskId, panelId, tabId);
    },
    [layoutState, taskId],
  );

  const handleCloseTabsToRight = useCallback(
    (panelId: string, tabId: string) => {
      layoutState.closeTabsToRight(taskId, panelId, tabId);
    },
    [layoutState, taskId],
  );

  const handleKeepTab = useCallback(
    (panelId: string, tabId: string) => {
      layoutState.keepTab(taskId, panelId, tabId);
    },
    [layoutState, taskId],
  );

  const handlePanelFocus = useCallback(
    (panelId: string) => {
      layoutState.setFocusedPanel(taskId, panelId);
    },
    [layoutState, taskId],
  );

  const handleAddTerminal = useCallback(
    (panelId: string) => {
      layoutState.addTerminalTab(taskId, panelId);
    },
    [layoutState, taskId],
  );

  const handleSplitPanel = useCallback(
    (panelId: string, direction: SplitDirection) => {
      const layout = usePanelLayoutStore.getState().getLayout(taskId);
      if (!layout) return;

      const findActiveTabId = (panelNode: PanelNode): string | null => {
        if (panelNode.type === "leaf" && panelNode.id === panelId) {
          return panelNode.content.activeTabId ?? null;
        }
        if (panelNode.type === "group") {
          for (const child of panelNode.children) {
            const result = findActiveTabId(child);
            if (result) return result;
          }
        }
        return null;
      };

      const activeTabId = findActiveTabId(layout.panelTree);
      if (activeTabId) {
        layoutState.splitPanel(
          taskId,
          activeTabId,
          panelId,
          panelId,
          direction,
        );
      }
    },
    [layoutState, taskId],
  );

  const handleLayout = useCallback(
    (groupId: string, sizes: number[]) => {
      layoutState.updateSizes(taskId, groupId, sizes);
    },
    [layoutState, taskId],
  );

  const renderNode = useCallback(
    (currentNode: PanelNode): React.ReactNode => {
      if (currentNode.type === "leaf") {
        return (
          <LeafNodeRenderer
            node={currentNode}
            taskId={taskId}
            task={task}
            closeTab={layoutState.closeTab}
            closeOtherTabs={handleCloseOtherTabs}
            closeTabsToRight={handleCloseTabsToRight}
            keepTab={handleKeepTab}
            draggingTabId={layoutState.draggingTabId}
            draggingTabPanelId={layoutState.draggingTabPanelId}
            onActiveTabChange={handleSetActiveTab}
            onPanelFocus={handlePanelFocus}
            onAddTerminal={handleAddTerminal}
            onSplitPanel={handleSplitPanel}
          />
        );
      }

      if (currentNode.type === "group") {
        return (
          <GroupNodeRenderer
            node={currentNode}
            setGroupRef={setGroupRef}
            onLayout={handleLayout}
            renderNode={renderNode}
          />
        );
      }

      return null;
    },
    [
      taskId,
      task,
      layoutState,
      handleSetActiveTab,
      handleCloseOtherTabs,
      handleCloseTabsToRight,
      handleKeepTab,
      handlePanelFocus,
      handleAddTerminal,
      handleSplitPanel,
      setGroupRef,
      handleLayout,
    ],
  );

  return <>{renderNode(node)}</>;
};

export const PanelLayout: React.FC<PanelLayoutProps> = ({ taskId, task }) => {
  const layout = usePanelLayoutStore((state) => state.getLayout(taskId));
  const initializeTask = usePanelLayoutStore((state) => state.initializeTask);
  const dragDropHandlers = useDragDropHandlers(taskId);

  usePanelKeyboardShortcuts(taskId);

  useEffect(() => {
    if (!layout) {
      initializeTask(taskId);
    }
  }, [taskId, layout, initializeTask]);

  if (!layout) {
    return null;
  }

  return (
    <DragDropProvider {...dragDropHandlers}>
      <PanelLayoutRenderer
        node={layout.panelTree}
        taskId={taskId}
        task={task}
      />
    </DragDropProvider>
  );
};
