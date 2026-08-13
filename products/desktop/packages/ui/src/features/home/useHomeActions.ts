import type { HomeRow } from "@posthog/core/home/homeRows";
import type { HomeStatus } from "@posthog/core/home/schemas";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { useCallback, useMemo } from "react";

const log = logger.scope("home-actions");

/**
 * What a row can do. One object for the whole table rather than closures per
 * row, so a poll that hands the list new row objects doesn't also hand every
 * row new props and re-render the screen.
 */
export interface HomeRowActions {
  open: (row: HomeRow) => void;
  fileToProject: (row: HomeRow, projectId: string | null) => void;
  /** Plans and todos only: the other kinds read their status off a run. */
  setNoteStatus: (row: HomeRow, status: HomeStatus) => void;
  remove: (row: HomeRow) => void;
}

/**
 * Opening a row goes wherever that kind of work already lives: a session to its
 * detail view inside its space, a canvas to the space's canvas view. A plan or
 * a todo has no page of its own yet, so it opens in place through `onOpenNote`.
 */
export function useHomeActions({
  onOpenNote,
}: {
  onOpenNote: (row: HomeRow) => void;
}): HomeRowActions {
  const fileWork = useHomeProjectsStore((state) => state.fileWork);
  const updateNote = useHomeProjectsStore((state) => state.updateNote);
  const deleteNote = useHomeProjectsStore((state) => state.deleteNote);

  const open = useCallback(
    (row: HomeRow) => {
      switch (row.kind) {
        case "session":
          if (row.task) {
            void openTask(row.task, { channelId: row.spaceId }).catch(
              (error: unknown) =>
                log.error("Failed to open session", { error }),
            );
          }
          return;
        case "canvas":
          navigateToChannelDashboard(row.spaceId, row.id);
          return;
        default:
          onOpenNote(row);
      }
    },
    [onOpenNote],
  );

  const fileToProject = useCallback(
    (row: HomeRow, projectId: string | null) => fileWork(row.id, projectId),
    [fileWork],
  );

  const setNoteStatus = useCallback(
    (row: HomeRow, status: HomeStatus) => updateNote(row.id, { status }),
    [updateNote],
  );

  const remove = useCallback(
    (row: HomeRow) => deleteNote(row.id),
    [deleteNote],
  );

  return useMemo(
    () => ({ open, fileToProject, setNoteStatus, remove }),
    [open, fileToProject, setNoteStatus, remove],
  );
}
