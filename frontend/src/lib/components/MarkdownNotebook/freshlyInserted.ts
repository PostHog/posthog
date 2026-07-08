/**
 * Node ids of components the local user just inserted (slash menu, shortcuts). Embedded
 * editors consult this on mount to decide whether they may steal focus: a freshly
 * inserted SQL block should focus its editor, but a block that is merely (re)mounting —
 * on notebook load, a remote merge, or a structural re-render — must never grab the
 * caret away from where the user is typing.
 */
const freshlyInsertedAt = new Map<string, number>()

/** Long enough to cover the mount after insertion; short enough that later remounts never refocus. */
const FRESH_INSERT_TTL_MS = 2000

export function markNotebookNodeFreshlyInserted(nodeId: string): void {
    freshlyInsertedAt.set(nodeId, Date.now())
}

export function wasNotebookNodeJustInserted(nodeId: string | null | undefined): boolean {
    if (!nodeId) {
        return false
    }
    const insertedAt = freshlyInsertedAt.get(nodeId)
    if (insertedAt === undefined) {
        return false
    }
    if (Date.now() - insertedAt > FRESH_INSERT_TTL_MS) {
        freshlyInsertedAt.delete(nodeId)
        return false
    }
    return true
}
