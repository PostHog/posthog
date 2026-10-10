import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import { useChannelTasksRunState } from "@posthog/ui/features/canvas/hooks/useChannelTasksRunState";
import { useScopedTaskSelectionStore } from "@posthog/ui/features/sidebar/TaskSelectionScope";
import { useBulkArchiveConfirm } from "@posthog/ui/features/sidebar/useBulkArchiveConfirm";
import { useClearSelectionOnEscape } from "@posthog/ui/features/sidebar/useClearSelectionOnEscape";
import { useMarqueeSelection } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import { useSidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import type { MouseEvent, RefObject } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";

export interface ChannelItemSelection {
  selectedTaskIds: string[];
  clearSelection: () => void;
  bulkActions: ReturnType<typeof useSidebarBulkActions>;
  archiveConfirm: ReturnType<typeof useBulkArchiveConfirm>;
  marquee: ReturnType<typeof useMarqueeSelection>;
  listAnchorRef: RefObject<HTMLDivElement | null>;
  onRowClick: (item: ChannelItemModel, event: MouseEvent) => void;
  selectFromClick: (taskId: string, event: MouseEvent) => boolean;
}

export function useChannelItemSelection({
  listItems,
  activeKey,
  open,
  marqueeFromRows = false,
}: {
  listItems: readonly ChannelItemModel[];
  activeKey: string | null;
  open: (item: ChannelItemModel) => void;
  marqueeFromRows?: boolean;
}): ChannelItemSelection {
  const selectableTaskIds = useMemo(
    () => listItems.filter((i) => i.kind === "task").map((i) => i.id),
    [listItems],
  );
  const selectionStore = useScopedTaskSelectionStore();
  const selectedTaskIds = selectionStore((s) => s.selectedTaskIds);
  const toggleTaskSelection = selectionStore((s) => s.toggleTaskSelection);
  const selectRange = selectionStore((s) => s.selectRange);
  const clearSelection = selectionStore((s) => s.clearSelection);
  const pruneSelection = selectionStore((s) => s.pruneSelection);
  useClearSelectionOnEscape();
  const listAnchorRef = useRef<HTMLDivElement | null>(null);
  const marquee = useMarqueeSelection(listAnchorRef, {
    startOnRows: marqueeFromRows,
  });

  useEffect(() => {
    pruneSelection(selectableTaskIds);
  }, [selectableTaskIds, pruneSelection]);

  const activeTaskId = activeKey?.startsWith("task:")
    ? activeKey.slice("task:".length)
    : null;

  const selectedTasks = useMemo(() => {
    const selected = new Set(selectedTaskIds);
    return listItems
      .filter(
        (i): i is ChannelItemModel & { task: Task } =>
          i.kind === "task" && i.task !== null && selected.has(i.id),
      )
      .map((i) => i.task);
  }, [listItems, selectedTaskIds]);
  const selectedTasksRunState = useChannelTasksRunState(selectedTasks);
  const bulkActions = useSidebarBulkActions(
    selectedTaskIds,
    selectedTasksRunState,
  );
  const archiveConfirm = useBulkArchiveConfirm(bulkActions);

  const selectFromClick = useCallback(
    (taskId: string, event: MouseEvent): boolean => {
      if (event.shiftKey) {
        event.preventDefault();
        selectRange(taskId, selectableTaskIds, activeTaskId);
        return true;
      }
      if (event.metaKey || event.ctrlKey) {
        event.preventDefault();
        toggleTaskSelection(taskId);
        return true;
      }
      clearSelection();
      return false;
    },
    [
      activeTaskId,
      clearSelection,
      selectRange,
      selectableTaskIds,
      toggleTaskSelection,
    ],
  );

  const onRowClick = (item: ChannelItemModel, event: MouseEvent) => {
    if (item.kind !== "task") {
      open(item);
      return;
    }
    if (!selectFromClick(item.id, event)) open(item);
  };

  return {
    selectedTaskIds,
    clearSelection,
    bulkActions,
    archiveConfirm,
    marquee,
    listAnchorRef,
    onRowClick,
    selectFromClick,
  };
}
