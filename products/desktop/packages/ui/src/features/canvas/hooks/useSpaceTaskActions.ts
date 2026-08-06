import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToCommandCenter } from "@posthog/ui/router/navigationBridge";
import { createContext, useContext, useMemo, useRef } from "react";

/**
 * What a session row in the space tree can do to its task, from its hover card
 * and its right-click menu. The same actions the space's own list offers, minus
 * the ones that need the list around them (inline rename), and minus canvases,
 * which the tree doesn't show.
 */
export interface SpaceTaskActions {
  togglePin: (item: ChannelItemModel) => void;
  archive: (item: ChannelItemModel) => void;
  /**
   * The handler for "Add to Command Center", or nothing when there's no free
   * cell or the task already holds one — which is what greys the item out.
   */
  commandCenterAssigner: (taskId: string) => (() => void) | undefined;
}

/**
 * Built once for the whole list rather than per row. Each of these hooks is a
 * mutation or a store subscription, and the tree can show dozens of session rows
 * at once; the object is also handed to memoized rows, so its identity has to
 * survive the list's own re-renders.
 */
export function useSpaceTaskActions(): SpaceTaskActions {
  const { togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask({ navigateSpace: "website" });
  const cells = useCommandCenterStore((state) => state.cells);
  const assignTask = useCommandCenterStore((state) => state.assignTask);

  // `archiveTask` is rebuilt every render; going through a ref is what keeps the
  // actions object below stable while still calling the current one.
  const archiveRef = useRef(archiveTask);
  archiveRef.current = archiveTask;

  return useMemo<SpaceTaskActions>(
    () => ({
      togglePin: (item) => {
        togglePin(item.id).catch(() => {
          toast.error("Couldn't update pin");
        });
      },
      archive: (item) => {
        void archiveRef.current({ taskId: item.id });
      },
      commandCenterAssigner: (taskId) => {
        if (cells.includes(taskId)) return undefined;
        const cellIndex = cells.findIndex((cell) => cell == null);
        if (cellIndex === -1) return undefined;
        return () => {
          assignTask(cellIndex, taskId);
          navigateToCommandCenter();
        };
      },
    }),
    [togglePin, cells, assignTask],
  );
}

/**
 * The list hands its rows one actions object through context rather than a prop:
 * the rows are memoized on their props, and threading this through the space
 * rows between them would put it in every one of those comparisons.
 */
export const SpaceTaskActionsContext = createContext<SpaceTaskActions | null>(
  null,
);

export function useSpaceTaskActionsContext(): SpaceTaskActions | null {
  return useContext(SpaceTaskActionsContext);
}
