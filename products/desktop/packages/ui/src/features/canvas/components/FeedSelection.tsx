import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import {
  type TaskRowBulkMenu,
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useChannelItemSelection } from "@posthog/ui/features/canvas/hooks/useChannelItemSelection";
import { MarqueeOverlay } from "@posthog/ui/features/sidebar/components/MarqueeOverlay";
import { SidebarBulkActionBar } from "@posthog/ui/features/sidebar/components/SidebarBulkActionBar";
import { useScopedTaskSelectionStore } from "@posthog/ui/features/sidebar/TaskSelectionScope";
import {
  createContext,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
} from "react";

interface FeedSelectionActions {
  selectFromClick: (taskId: string, event: MouseEvent) => boolean;
  clearSelection: () => void;
}

const FeedSelectionActionsContext = createContext<FeedSelectionActions | null>(
  null,
);
const FeedBulkMenuContext = createContext<TaskRowBulkMenu | null>(null);

export function FeedSelection({
  items,
  onOpenThread,
  children,
}: {
  items: readonly ChannelItemModel[];
  onOpenThread: (task: Task) => void;
  children: ReactNode;
}) {
  const open = useCallback(
    (item: ChannelItemModel) => {
      if (item.task) onOpenThread(item.task);
    },
    [onOpenThread],
  );
  const {
    selectedTaskIds,
    clearSelection,
    bulkActions,
    archiveConfirm,
    marquee,
    listAnchorRef,
    selectFromClick,
  } = useChannelItemSelection({
    listItems: items,
    activeKey: null,
    open,
    marqueeFromRows: true,
  });
  const actions = useMemo(
    () => ({ selectFromClick, clearSelection }),
    [selectFromClick, clearSelection],
  );
  const bulkMenu = useMemo<TaskRowBulkMenu | null>(
    () =>
      selectedTaskIds.length > 1
        ? {
            actions: bulkActions,
            onArchive: archiveConfirm.requestArchive,
            withCommandCenter: false,
          }
        : null,
    [archiveConfirm.requestArchive, bulkActions, selectedTaskIds.length],
  );

  return (
    <FeedSelectionActionsContext.Provider value={actions}>
      <FeedBulkMenuContext.Provider value={bulkMenu}>
        <div ref={listAnchorRef} className="relative">
          {children}
          <MarqueeOverlay rect={marquee} />
        </div>
        <div className="sticky bottom-3 z-20">
          <SidebarBulkActionBar
            actions={bulkActions}
            onClearSelection={clearSelection}
            onArchive={archiveConfirm.requestArchive}
            withCommandCenter={false}
            className="mt-3 rounded-md border shadow-md"
          />
        </div>
        {archiveConfirm.dialog}
      </FeedBulkMenuContext.Provider>
    </FeedSelectionActionsContext.Provider>
  );
}

export function useFeedRowSelection(
  taskId: string,
  selectable: boolean,
): { actions: FeedSelectionActions | null; selected: boolean } {
  const context = useContext(FeedSelectionActionsContext);
  const actions = selectable ? context : null;
  const selected = useScopedTaskSelectionStore()(
    (s) => actions !== null && s.selectedTaskIds.includes(taskId),
  );
  return { actions, selected };
}

export function FeedRowContextMenu({
  menu,
  selected,
  onClearSelection,
  children,
}: {
  menu: TaskRowMenuProps;
  selected: boolean;
  onClearSelection?: () => void;
  children: ReactNode;
}) {
  const bulk = useContext(FeedBulkMenuContext);
  const onOpenChange = useCallback(
    (open: boolean) => {
      if (open && !selected) onClearSelection?.();
    },
    [onClearSelection, selected],
  );
  return (
    <TaskRowContextMenu
      menu={menu}
      bulk={selected ? bulk : null}
      onOpenChange={onOpenChange}
    >
      {children}
    </TaskRowContextMenu>
  );
}
