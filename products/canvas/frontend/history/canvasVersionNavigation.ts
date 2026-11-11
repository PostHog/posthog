// Undo and redo step through a canvas's version history (newest first) relative to the head.
// After a revert the head can sit in the middle of the list, not at versions[0].
// Ported from PostHog Desktop's canvasVersionNavigation.ts, so both hosts step the same way.

export interface CanvasVersionNavigation {
    /** Index of the head version in the newest-first list. 0 when the head is unknown. */
    headIndex: number
    /** Index being viewed: the browsed version when known, else the head. */
    currentIndex: number
    canUndo: boolean
    canRedo: boolean
    /** The next older version to browse on undo. Null at the oldest version. */
    undoTargetId: string | null
    /** The next newer version to browse on redo. Null means step onto the head, which ends the browse. */
    redoTargetId: string | null
}

export function canvasVersionNavigation(args: {
    /** Version history, newest first. */
    versions: readonly { id: string }[]
    /** The canvas's current head version id. */
    headVersionId: string | null | undefined
    /** The version being browsed, or null when viewing the head. */
    browseVersionId: string | null
}): CanvasVersionNavigation {
    const { versions, headVersionId, browseVersionId } = args

    const headIdx = headVersionId ? versions.findIndex((version) => version.id === headVersionId) : -1
    const headIndex = headIdx === -1 ? 0 : headIdx

    const browsing = !!browseVersionId
    const browseIndex = browseVersionId ? versions.findIndex((version) => version.id === browseVersionId) : -1
    const currentIndex = browsing && browseIndex !== -1 ? browseIndex : headIndex

    const canUndo = versions.length > 0 && currentIndex < versions.length - 1
    const canRedo = browsing && currentIndex > headIndex

    const undoTargetId = canUndo ? (versions[currentIndex + 1]?.id ?? null) : null
    const redoIndex = currentIndex - 1
    const redoTargetId = redoIndex <= headIndex ? null : (versions[redoIndex]?.id ?? null)

    return { headIndex, currentIndex, canUndo, canRedo, undoTargetId, redoTargetId }
}

/**
 * Whether a browse points at a version the canvas no longer offers, for example one pruned
 * while the canvas was open. Published versions and staged drafts are both valid targets.
 * A history that is still loading is not evidence that the version is gone.
 */
export function shouldClearCanvasBrowse(args: {
    browseTargetIds: readonly string[]
    loading: boolean
    browseVersionId: string | null
}): boolean {
    const { browseTargetIds, loading, browseVersionId } = args
    return !!browseVersionId && !loading && browseTargetIds.length > 0 && !browseTargetIds.includes(browseVersionId)
}
