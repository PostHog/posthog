// Pure undo/redo arithmetic over a canvas's server-side version history
// (newest first). Undo/redo step through the list relative to the HEAD —
// which, after a revert, may sit mid-list rather than at versions[0].

export interface CanvasVersionNavigation {
  /** Index of the head version in the (newest-first) list; 0 when unknown. */
  headIndex: number;
  /** Index being viewed: the browsed version when known, else the head. */
  currentIndex: number;
  canUndo: boolean;
  canRedo: boolean;
  /** The next-older version to browse on undo; null when at the oldest. */
  undoTargetId: string | null;
  /** The next-newer version to browse on redo; null = step onto (or past)
   * the head, which ends the browse — back to live. Only meaningful while
   * `canRedo`. */
  redoTargetId: string | null;
}

export function canvasVersionNavigation(args: {
  /** Version history, newest first. */
  versions: readonly { id: string }[];
  /** The record's current head version id. */
  headVersionId: string | null | undefined;
  /** The version being browsed, or null when viewing the head/live output. */
  browseVersionId: string | null;
}): CanvasVersionNavigation {
  const { versions, headVersionId, browseVersionId } = args;

  const headIdx = headVersionId
    ? versions.findIndex((v) => v.id === headVersionId)
    : -1;
  const headIndex = headIdx === -1 ? 0 : headIdx;

  const browsing = !!browseVersionId;
  const browseIndex = browseVersionId
    ? versions.findIndex((v) => v.id === browseVersionId)
    : -1;
  const currentIndex = browsing && browseIndex !== -1 ? browseIndex : headIndex;

  const canUndo = versions.length > 0 && currentIndex < versions.length - 1;
  const canRedo = browsing && currentIndex > headIndex;

  const undoTargetId = canUndo
    ? (versions[currentIndex + 1]?.id ?? null)
    : null;
  // Stepping onto (or past) the head ends the browse — back to live.
  const redoIndex = currentIndex - 1;
  const redoTargetId =
    redoIndex <= headIndex ? null : (versions[redoIndex]?.id ?? null);

  return {
    headIndex,
    currentIndex,
    canUndo,
    canRedo,
    undoTargetId,
    redoTargetId,
  };
}

/**
 * Whether an active browse points at a version the history no longer contains
 * (e.g. it was pruned server-side while the canvas was open) and should be
 * cleared. A still-loading or empty history is not evidence of absence.
 */
export function shouldClearCanvasBrowse(args: {
  versions: readonly { id: string }[];
  versionsLoading: boolean;
  browseVersionId: string | null;
}): boolean {
  const { versions, versionsLoading, browseVersionId } = args;
  return (
    !!browseVersionId &&
    !versionsLoading &&
    versions.length > 0 &&
    !versions.some((v) => v.id === browseVersionId)
  );
}
