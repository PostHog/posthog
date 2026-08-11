/**
 * The selection bar's pin action: a mixed selection pins rather than unpins,
 * so the action is only destructive to existing pins once everything selected
 * is already pinned. `toToggle` holds only the ids whose current state
 * differs from the target, so pinning a mixed selection never unpins the
 * already-pinned ones.
 */
export function resolveBulkPinTargets(
  selectedIds: Iterable<string>,
  isPinned: (taskId: string) => boolean,
): { targetPinned: boolean; toToggle: string[] } {
  const ids = Array.from(selectedIds);
  const targetPinned = ids.some((id) => !isPinned(id));
  return {
    targetPinned,
    toToggle: ids.filter((id) => isPinned(id) !== targetPinned),
  };
}
