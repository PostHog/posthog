import { type Options, useHotkeys } from "react-hotkeys-hook";
import { SHORTCUTS } from "../../command/keyboard-shortcuts";
import { usePanelLayoutStore } from "../panelLayoutStore";
import { getLeafPanel } from "../panelStoreHelpers";

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

      const state = usePanelLayoutStore.getState();
      const currentLayout = state.getLayout(taskId);
      const currentFocusedPanelId = currentLayout?.focusedPanelId;
      const panelTree = currentLayout?.panelTree;

      if (!currentFocusedPanelId || !panelTree) return;

      const keyPressed = handler.keys?.[0];
      if (!keyPressed) return;

      const index = parseInt(keyPressed, 10) - 1;
      const panel = getLeafPanel(panelTree, currentFocusedPanelId);

      if (panel?.content.tabs[index]) {
        state.setActiveTab(
          taskId,
          currentFocusedPanelId,
          panel.content.tabs[index].id,
        );
      }
    },
    hotkeyOptions,
    [taskId],
  );

  useHotkeys(
    SHORTCUTS.CLOSE_TAB,
    (event) => {
      event.preventDefault();

      const state = usePanelLayoutStore.getState();
      const currentLayout = state.getLayout(taskId);
      const currentFocusedPanelId = currentLayout?.focusedPanelId;
      const panelTree = currentLayout?.panelTree;

      if (!currentFocusedPanelId || !panelTree) return;

      const panel = getLeafPanel(panelTree, currentFocusedPanelId);
      if (!panel) return;

      const activeTab = panel.content.tabs.find(
        (t) => t.id === panel.content.activeTabId,
      );

      if (activeTab && activeTab.closeable !== false) {
        state.closeTab(taskId, currentFocusedPanelId, activeTab.id);
      }
    },
    hotkeyOptions,
    [taskId],
  );

  useHotkeys(
    SHORTCUTS.SPLIT_PANEL,
    (event) => {
      event.preventDefault();

      const state = usePanelLayoutStore.getState();
      const focusedPanelId = state.getLayout(taskId)?.focusedPanelId;
      if (!focusedPanelId) return;

      state.splitPanelWithCopy(taskId, focusedPanelId, "right", "shortcut");
    },
    hotkeyOptions,
    [taskId],
  );

  useHotkeys(
    SHORTCUTS.CLOSE_PANEL,
    (event) => {
      event.preventDefault();

      const state = usePanelLayoutStore.getState();
      const focusedPanelId = state.getLayout(taskId)?.focusedPanelId;
      if (!focusedPanelId) return;

      state.closePanel(taskId, focusedPanelId, "shortcut");
    },
    hotkeyOptions,
    [taskId],
  );
}
