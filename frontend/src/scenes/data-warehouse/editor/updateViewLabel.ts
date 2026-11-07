/**
 * Saving a materialized view also re-runs its materialization, so the label has to warn about that.
 * Shared because the inline diff's accept button has to read the same as the button that opened it.
 */
export function updateViewLabel(isMaterializedView: boolean): string {
    return isMaterializedView ? 'Update and re-materialize view' : 'Update view'
}
