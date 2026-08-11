// Whether the canvas's right-hand dock is mounted, and why. Two independent
// reasons, because the dock serves two modes: editing a canvas, and reading the
// comments/agent chat of one you're only viewing.

export interface CanvasSidePanelVisibility {
  /** The edit-mode dock: there's a canvas to change, or a run to watch. */
  editing: boolean;
  /** The on-demand dock in view mode, opened from the breadcrumb's Comments
   * button. Held open by its own state rather than by which tab is showing, so
   * switching tabs inside it can't tear it down. */
  viewing: boolean;
}

export function canvasSidePanelVisibility(args: {
  /** Whether the canvas is being edited. */
  interactive: boolean;
  /** Whether the canvas has any published source or artifact. */
  hasContent: boolean;
  /** Whether a generation/edit run is in flight or just submitted. */
  hasActiveTask: boolean;
  /** The generating-canvas default: the run's chat is the only content there
   * is, so the dock opens in view mode too. */
  generatingPanelOpen: boolean;
  /** Whether the dock was opened while viewing the canvas. */
  viewOpen: boolean;
  /** Whether the dock is minimized to the rail. */
  collapsed: boolean;
  /** Whether a task backs this canvas's comments and agent chat. */
  hasCommentTask: boolean;
}): CanvasSidePanelVisibility {
  return {
    editing:
      (args.interactive && (args.hasContent || args.hasActiveTask)) ||
      args.generatingPanelOpen,
    viewing: args.viewOpen && !args.collapsed && args.hasCommentTask,
  };
}
