import { useService } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo } from "react";
import { useSetHeaderContent } from "../../../hooks/useSetHeaderContent";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
} from "../../notifications/identifiers";
import { useTaskViewed } from "../../sidebar/useTaskViewed";
import { useCommandCenterStore } from "../commandCenterStore";
import { useAutofillCommandCenter } from "../hooks/useAutofillCommandCenter";
import { useCommandCenterData } from "../hooks/useCommandCenterData";
import { CommandCenterGrid } from "./CommandCenterGrid";
import { CommandCenterToolbar } from "./CommandCenterToolbar";

export function CommandCenterView() {
  const layout = useCommandCenterStore((s) => s.layout);
  const { cells, summary } = useCommandCenterData();
  const { markAsViewed, timestamps } = useTaskViewed();
  const activeView = useService<IActiveView>(ACTIVE_VIEW_PROVIDER);

  useAutofillCommandCenter();

  // Tracked on arrival rather than in the navigation bridge: the rail returns
  // to a remembered page by href, so a bridge-side event would miss every pick
  // after the first, as would a deep link or the back button.
  useEffect(() => {
    track(ANALYTICS_EVENTS.COMMAND_CENTER_VIEWED);
  }, []);

  // A cell whose task has been deleted holds a dead id, so occupancy is judged
  // on what actually renders — Optimize then packs the grid and drops the rest.
  const occupiedCellIndices = useMemo(() => {
    const indices: number[] = [];
    for (const cell of cells) {
      if (cell.task || cell.canvasId || cell.terminalId || cell.isBrainrot) {
        indices.push(cell.cellIndex);
      }
    }
    return indices;
  }, [cells]);

  const visibleTaskIdsKey = cells
    .map((c) => c.taskId)
    .filter(Boolean)
    .join(",");
  const visibleTaskStateKey = cells
    .map((c) =>
      c.taskId
        ? `${c.taskId}:${timestamps[c.taskId]?.lastActivityAt ?? ""}`
        : "",
    )
    .join(",");

  useEffect(() => {
    if (!visibleTaskStateKey || !activeView.hasFocus()) return;
    for (const taskId of visibleTaskIdsKey.split(",")) {
      markAsViewed(taskId);
    }
  }, [activeView, visibleTaskIdsKey, visibleTaskStateKey, markAsViewed]);

  // Root-level page: no breadcrumb row. Its own toolbar names the view, and
  // there's no parent space to walk back to, so the bar was an empty frame.
  // (Pushing null also collapses the row inside the Channels space, where
  // ShellLayout renders whatever the active view puts in the header store.)
  useSetHeaderContent(null);

  return (
    <div className="flex h-full flex-col">
      <CommandCenterToolbar
        summary={summary}
        occupiedCellIndices={occupiedCellIndices}
      />
      <div className="min-h-0 flex-1">
        <CommandCenterGrid layout={layout} cells={cells} />
      </div>
    </div>
  );
}
