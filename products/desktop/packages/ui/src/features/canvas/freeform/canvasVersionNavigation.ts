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
 * The draft to auto-open: the newest draft whose build is ready and hasn't
 * been seen ready before. Staging a draft is the review-flow counterpart of a
 * publish, which swaps the canvas the moment its build lands; opening the
 * finished draft gives it the same arrival moment instead of leaving it
 * hidden behind the Drafts menu. Returns null when nothing newly finished.
 */
export function freshReadyDraftId(
  seenReady: ReadonlySet<string>,
  drafts: readonly { versionId: string; buildStatus?: string | null }[],
): string | null {
  const fresh = drafts.find(
    (draft) => draft.buildStatus === "ready" && !seenReady.has(draft.versionId),
  );
  return fresh?.versionId ?? null;
}

/**
 * Whether an active browse points at a version the canvas no longer offers
 * (e.g. it was pruned server-side while the canvas was open) and should be
 * cleared. `browseTargetIds` is every id that is a valid browse target —
 * published versions and staged drafts alike (drafts are a valid preview
 * target even though they are excluded from the published history). A
 * still-loading history is not evidence of absence.
 */
export function shouldClearCanvasBrowse(args: {
  browseTargetIds: readonly string[];
  loading: boolean;
  browseVersionId: string | null;
}): boolean {
  const { browseTargetIds, loading, browseVersionId } = args;
  return (
    !!browseVersionId &&
    !loading &&
    browseTargetIds.length > 0 &&
    !browseTargetIds.includes(browseVersionId)
  );
}
