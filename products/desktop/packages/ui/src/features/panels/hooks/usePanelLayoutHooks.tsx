import {
  ChartLineUp,
  ChatCenteredText,
  FileText,
  Scroll,
  Terminal,
} from "@phosphor-icons/react";
import { resolveTabAbsolutePath } from "@posthog/core/panels/resolveTabPath";
import type { Task } from "@posthog/shared/domain-types";
import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ImperativePanelGroupHandle } from "react-resizable-panels";
import { FileIcon } from "../../../primitives/FileIcon";
import { ActionTabIcon } from "../../actions/ActionTabIcon";
import { useCwd } from "../../sidebar/useCwd";
import { TabContentRenderer } from "../../task-detail/components/TabContentRenderer";
import type { SplitDirection } from "../panelLayoutStore";
import { usePanelLayoutStore } from "../panelLayoutStore";
import { shouldUpdateSizes } from "../panelLayoutUtils";
import type { PanelNode, Tab } from "../panelTypes";

export interface PanelLayoutState {
  updateSizes: (taskId: string, groupId: string, sizes: number[]) => void;
  setActiveTab: (taskId: string, panelId: string, tabId: string) => void;
  closeTab: (taskId: string, panelId: string, tabId: string) => void;
  closeOtherTabs: (taskId: string, panelId: string, tabId: string) => void;
  closeTabsToRight: (taskId: string, panelId: string, tabId: string) => void;
  keepTab: (taskId: string, panelId: string, tabId: string) => void;
  setFocusedPanel: (taskId: string, panelId: string) => void;
  addTerminalTab: (taskId: string, panelId: string) => void;
  splitPanel: (
    taskId: string,
    tabId: string,
    sourcePanelId: string,
    targetPanelId: string,
    direction: SplitDirection,
  ) => void;
  draggingTabId: string | null;
  draggingTabPanelId: string | null;
  focusedPanelId: string | null;
}

export function usePanelLayoutState(taskId: string): PanelLayoutState {
  return usePanelLayoutStore(
    useCallback(
      (state) => ({
        updateSizes: state.updateSizes,
        setActiveTab: state.setActiveTab,
        closeTab: state.closeTab,
        closeOtherTabs: state.closeOtherTabs,
        closeTabsToRight: state.closeTabsToRight,
        keepTab: state.keepTab,
        setFocusedPanel: state.setFocusedPanel,
        addTerminalTab: state.addTerminalTab,
        splitPanel: state.splitPanel,
        draggingTabId: state.getLayout(taskId)?.draggingTabId ?? null,
        draggingTabPanelId: state.getLayout(taskId)?.draggingTabPanelId ?? null,
        focusedPanelId: state.getLayout(taskId)?.focusedPanelId ?? null,
      }),
      [taskId],
    ),
  );
}

export function usePanelGroupRefs() {
  const groupRefs = useRef<Map<string, ImperativePanelGroupHandle>>(new Map());

  const setGroupRef = useCallback(
    (groupId: string, ref: ImperativePanelGroupHandle | null) => {
      if (ref) {
        groupRefs.current.set(groupId, ref);
      } else {
        groupRefs.current.delete(groupId);
      }
    },
    [],
  );

  return { groupRefs, setGroupRef };
}

export function useTabInjection(
  tabs: Tab[],
  panelId: string,
  taskId: string,
  task: Task,
  closeTab: (taskId: string, panelId: string, tabId: string) => void,
): Tab[] {
  const repoPath = useCwd(taskId) ?? "";

  return useMemo(
    () =>
      tabs.map((tab) => {
        let updatedData = tab.data;
        if (tab.data.type === "file") {
          updatedData = {
            ...tab.data,
            absolutePath: resolveTabAbsolutePath(
              tab.data.relativePath,
              repoPath,
            ),
            repoPath,
          };
        }

        let icon = tab.icon;
        if (!icon) {
          if (tab.data.type === "file") {
            const filename = tab.data.relativePath.split("/").pop() || "";
            icon = <FileIcon filename={filename} size={14} />;
          } else if (tab.data.type === "terminal") {
            icon = <Terminal size={14} />;
          } else if (tab.data.type === "logs") {
            icon = <ChatCenteredText size={14} />;
          } else if (tab.data.type === "action") {
            icon = <ActionTabIcon actionId={tab.data.actionId} />;
          } else if (tab.data.type === "context") {
            icon = <FileText size={14} />;
          } else if (tab.data.type === "canvas-instructions") {
            icon = <Scroll size={14} />;
          } else if (tab.data.type === "autoresearch") {
            icon = <ChartLineUp size={14} />;
          }
        }

        const updatedTab = {
          ...tab,
          data: updatedData,
          icon,
        };

        return {
          ...updatedTab,
          component: (
            <TabContentRenderer tab={updatedTab} taskId={taskId} task={task} />
          ),
          onClose: tab.closeable
            ? () => {
                closeTab(taskId, panelId, tab.id);
              }
            : undefined,
        };
      }),
    [tabs, panelId, taskId, task, closeTab, repoPath],
  );
}

function syncSizesToLibrary(
  node: PanelNode,
  groupRefs: Map<string, ImperativePanelGroupHandle>,
): void {
  if (node.type === "group" && node.sizes) {
    const groupRef = groupRefs.get(node.id);
    if (groupRef) {
      const currentLayout = groupRef.getLayout();

      if (shouldUpdateSizes(currentLayout, node.sizes)) {
        groupRef.setLayout(node.sizes);
      }
    }

    for (const child of node.children) {
      syncSizesToLibrary(child, groupRefs);
    }
  }
}

export function usePanelSizeSync(
  node: PanelNode,
  groupRefs: Map<string, ImperativePanelGroupHandle>,
): void {
  useEffect(() => {
    syncSizesToLibrary(node, groupRefs);
  }, [node, groupRefs]);
}
