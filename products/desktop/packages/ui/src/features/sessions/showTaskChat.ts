import { useReviewNavigationStore } from "../code-review/reviewNavigationStore";
import { DEFAULT_TAB_IDS } from "../panels/panelConstants";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { findTabInTree } from "../panels/panelTree";

export function showTaskChat(taskId: string): void {
  const { getReviewMode, setReviewMode } = useReviewNavigationStore.getState();
  if (getReviewMode(taskId) === "expanded") {
    setReviewMode(taskId, "split");
  }

  const { taskLayouts, setActiveTab } = usePanelLayoutStore.getState();
  const layout = taskLayouts[taskId];
  if (layout) {
    const result = findTabInTree(layout.panelTree, DEFAULT_TAB_IDS.LOGS);
    if (result) {
      setActiveTab(taskId, result.panelId, DEFAULT_TAB_IDS.LOGS);
    }
  }
}
