import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToCommandCenter } from "@posthog/ui/router/navigationBridge";
import { createContext, useContext, useEffect, useMemo, useRef } from "react";

/**
 * What a session row in the space tree can do to its task, from its hover card
 * and its right-click menu. The same actions the space's own list offers,
 * without the ones that need the list around them (inline rename) and without
 * canvases, which the tree doesn't show.
 */
export interface SpaceTaskActions {
  togglePin: (item: ChannelItemModel) => void;
  archive: (item: ChannelItemModel) => void;
  /**
   * The handler for "Add to Command Center", or nothing when every cell is
   * taken or this task already holds one, which is what greys the item out.
   */
  commandCenterAssigner: (taskId: string) => (() => void) | undefined;
}

/**
 * Built once for the whole list rather than per row: each of these hooks is a
 * mutation or a store subscription, and the tree can show dozens of session
 * rows at once. The object is handed to memoized rows, so its identity has to
 * survive the list's own re-renders.
 */
export function useSpaceTaskActions(): SpaceTaskActions {
  const { togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask();
  const cells = useCommandCenterStore((state) => state.cells);
  const assignTask = useCommandCenterStore((state) => state.assignTask);

  // `archiveTask` is a new function every render, so it goes through a ref to
  // keep the object below stable while still calling the current one. The ref
  // is written after the commit, not during the render, because a render can be
  // thrown away and a row only reads this from an event handler.
  const archiveRef = useRef(archiveTask);
  useEffect(() => {
    archiveRef.current = archiveTask;
  });

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
 * The list hands its rows one actions object through context rather than a
 * prop, because the rows are memoized on their props and threading it through
 * the space rows between them would put it in every one of those comparisons.
 */
const SpaceTaskActionsContext = createContext<SpaceTaskActions | null>(null);

export const SpaceTaskActionsProvider = SpaceTaskActionsContext.Provider;

export function useSpaceTaskActionsContext(): SpaceTaskActions {
  const actions = useContext(SpaceTaskActionsContext);
  if (!actions) {
    throw new Error("Space task rows must render inside ChannelsList");
  }
  return actions;
}
