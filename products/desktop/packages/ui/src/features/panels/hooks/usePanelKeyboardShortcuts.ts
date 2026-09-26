import { type Options, useHotkeys } from "react-hotkeys-hook";
import { SHORTCUTS } from "../../command/keyboard-shortcuts";
import { usePanelLayoutStore } from "../panelLayoutStore";
import { getLeafPanel } from "../panelStoreHelpers";

function focusedPanel(taskId: string) {
  const state = usePanelLayoutStore.getState();
  const layout = state.getLayout(taskId);
  const panelId = layout?.focusedPanelId;
  if (!layout || !panelId) return null;
  return { state, panelId, panel: getLeafPanel(layout.panelTree, panelId) };
}

export function usePanelKeyboardShortcuts(taskId: string): void {
  const layout = usePanelLayoutStore((state) => state.getLayout(taskId));

  const hotkeyOptions: Options = {
    enabled: !!layout,
    enableOnFormTags: ["INPUT", "TEXTAREA", "SELECT"],
    enableOnContentEditable: true,
    scopes: ["taskDetail"],
  };

  useHotkeys(
    SHORTCUTS.SWITCH_TAB,
    (event, handler) => {
      event.preventDefault();
      const focused = focusedPanel(taskId);
      const index = parseInt(handler.keys?.[0] ?? "", 10) - 1;
      const tab = focused?.panel?.content.tabs[index];
      if (focused && tab) {
        focused.state.setActiveTab(taskId, focused.panelId, tab.id);
      }
    },
    hotkeyOptions,
    [taskId],
  );

  useHotkeys(
    SHORTCUTS.CLOSE_TAB,
    (event) => {
      event.preventDefault();
      const focused = focusedPanel(taskId);
      const content = focused?.panel?.content;
      const activeTab = content?.tabs.find((t) => t.id === content.activeTabId);
      if (focused && activeTab && activeTab.closeable !== false) {
        focused.state.closeTab(taskId, focused.panelId, activeTab.id);
      }
    },
    hotkeyOptions,
    [taskId],
  );

  useHotkeys(
    SHORTCUTS.SPLIT_PANEL,
    (event) => {
      event.preventDefault();
      const focused = focusedPanel(taskId);
      focused?.state.splitPanelWithCopy(
        taskId,
        focused.panelId,
        "right",
        "shortcut",
      );
    },
    hotkeyOptions,
    [taskId],
  );

  useHotkeys(
    SHORTCUTS.CLOSE_PANEL,
    (event) => {
      event.preventDefault();
      const focused = focusedPanel(taskId);
      focused?.state.closePanel(taskId, focused.panelId, "shortcut");
    },
    hotkeyOptions,
    [taskId],
  );
}
