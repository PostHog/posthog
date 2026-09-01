import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import { useChannelTasksRunState } from "@posthog/ui/features/canvas/hooks/useChannelTasksRunState";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { useBulkArchiveConfirm } from "@posthog/ui/features/sidebar/useBulkArchiveConfirm";
import { useClearSelectionOnEscape } from "@posthog/ui/features/sidebar/useClearSelectionOnEscape";
import { useMarqueeSelection } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import { useSidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import type { MouseEvent, RefObject } from "react";
import { useEffect, useMemo, useRef } from "react";

export interface ChannelItemSelection {
  selectedTaskIds: string[];
  clearSelection: () => void;
  bulkActions: ReturnType<typeof useSidebarBulkActions>;
  archiveConfirm: ReturnType<typeof useBulkArchiveConfirm>;
  marquee: ReturnType<typeof useMarqueeSelection>;
  listAnchorRef: RefObject<HTMLDivElement | null>;
  onRowClick: (item: ChannelItemModel, event: MouseEvent) => void;
}

export function useChannelItemSelection({
  listItems,
  activeKey,
  open,
}: {
  listItems: readonly ChannelItemModel[];
  activeKey: string | null;
  open: (item: ChannelItemModel) => void;
}): ChannelItemSelection {
  const selectableTaskIds = useMemo(
    () => listItems.filter((i) => i.kind === "task").map((i) => i.id),
    [listItems],
  );
  const selectedTaskIds = useTaskSelectionStore((s) => s.selectedTaskIds);
  const toggleTaskSelection = useTaskSelectionStore(
    (s) => s.toggleTaskSelection,
  );
  const selectRange = useTaskSelectionStore((s) => s.selectRange);
  const clearSelection = useTaskSelectionStore((s) => s.clearSelection);
  const pruneSelection = useTaskSelectionStore((s) => s.pruneSelection);
  useClearSelectionOnEscape();
  const listAnchorRef = useRef<HTMLDivElement | null>(null);
  const marquee = useMarqueeSelection(listAnchorRef);

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

  const onRowClick = (item: ChannelItemModel, event: MouseEvent) => {
    if (item.kind !== "task") {
      open(item);
      return;
    }
    if (event.shiftKey) {
      event.preventDefault();
      selectRange(item.id, selectableTaskIds, activeTaskId);
      return;
    }
    if (event.metaKey || event.ctrlKey) {
      event.preventDefault();
      toggleTaskSelection(item.id);
      return;
    }
    clearSelection();
    open(item);
  };

  return {
    selectedTaskIds,
    clearSelection,
    bulkActions,
    archiveConfirm,
    marquee,
    listAnchorRef,
    onRowClick,
  };
}
