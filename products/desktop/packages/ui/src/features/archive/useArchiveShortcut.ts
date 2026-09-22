import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useId, useLayoutEffect } from "react";
import { useHotkeys } from "react-hotkeys-hook";

type ArchiveShortcutPriority = "visible-task" | "active-menu";

const PRIORITY: Record<ArchiveShortcutPriority, number> = {
  "visible-task": 0,
  "active-menu": 1,
};

let activationOrder = 0;
const activeTargets = new Map<
  string,
  { priority: number; activationOrder: number }
>();

function registerTarget(
  id: string,
  priority: ArchiveShortcutPriority,
): () => void {
  activationOrder += 1;
  activeTargets.set(id, {
    priority: PRIORITY[priority],
    activationOrder,
  });
  return () => activeTargets.delete(id);
}

function isActiveTarget(id: string): boolean {
  let activeId: string | null = null;
  let activePriority = -1;
  let activeOrder = -1;

  for (const [candidateId, target] of activeTargets) {
    if (
      target.priority > activePriority ||
      (target.priority === activePriority &&
        target.activationOrder > activeOrder)
    ) {
      activeId = candidateId;
      activePriority = target.priority;
      activeOrder = target.activationOrder;
    }
  }

  return activeId === id;
}

export function useArchiveShortcut({
  onArchive,
  enabled,
  priority,
  scopes,
}: {
  onArchive: (() => void) | undefined;
  enabled: boolean;
  priority: ArchiveShortcutPriority;
  scopes?: string | readonly string[];
}): void {
  const targetId = useId();
  const active = enabled && onArchive !== undefined;

  useLayoutEffect(() => {
    if (!active) return;
    return registerTarget(targetId, priority);
  }, [active, priority, targetId]);

  useHotkeys(
    SHORTCUTS.ARCHIVE_TASK,
    (event) => {
      if (event.repeat) return;
      if (!isActiveTarget(targetId)) return;
      event.preventDefault();
      onArchive?.();
    },
    {
      enabled: active,
      enableOnContentEditable: true,
      enableOnFormTags: true,
      scopes,
    },
    [onArchive, targetId],
  );
}
