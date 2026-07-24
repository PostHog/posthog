/** Editor wrapper that hands keyboard focus to the subagent status footer on Down/Up/Escape. */

import {
  CustomEditor,
  type KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import {
  type EditorTheme,
  Key,
  matchesKey,
  type TUI,
} from "@earendil-works/pi-tui";
import { hasActiveWorkflows } from "../workflow/status-registry";
import {
  blur,
  focusFromEditor,
  getFocusedWorkflowId,
  hasActiveAgentRuns,
  isFocused,
  moveDown,
  moveUp,
} from "./status-registry";

export class SubagentStatusEditor extends CustomEditor {
  constructor(
    tui: TUI,
    theme: EditorTheme,
    keybindings: KeybindingsManager,
    private readonly onOpenOverlay: (workflowId?: string) => void,
  ) {
    super(tui, theme, keybindings);
  }

  override handleInput(data: string): void {
    if (isFocused()) {
      this.handleFooterFocusedInput(data);
      return;
    }

    if (
      matchesKey(data, Key.down) &&
      this.getText() === "" &&
      (hasActiveAgentRuns() || hasActiveWorkflows())
    ) {
      if (focusFromEditor()) {
        this.tui.requestRender();
        return;
      }
    }

    super.handleInput(data);
  }

  private handleFooterFocusedInput(data: string): void {
    if (matchesKey(data, Key.down)) {
      moveDown();
      this.tui.requestRender();
      return;
    }
    if (matchesKey(data, Key.up)) {
      moveUp();
      this.tui.requestRender();
      return;
    }
    if (matchesKey(data, Key.enter)) {
      this.onOpenOverlay(getFocusedWorkflowId());
      return;
    }
    if (matchesKey(data, Key.escape)) {
      blur();
      this.tui.requestRender();
      return;
    }
    if (matchesKey(data, Key.ctrl("c")) || matchesKey(data, Key.ctrl("d"))) {
      super.handleInput(data);
    }
  }
}
