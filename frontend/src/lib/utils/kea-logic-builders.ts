import { BuiltLogic, afterMount } from 'kea'

/**
 * Some kea logics are used heavily across multiple areas so we keep it mounted once loaded with this trick.
 */
export function permanentlyMount(): (logic: BuiltLogic) => void {
    return (logic) => {
        afterMount(() => {
            if (!logic.cache._permanentMount) {
                logic.cache._permanentMount = true
                logic.mount()
            }
        })(logic)
    }
}

// Abort reasons for requests a logic cancels on purpose, passed as the message of an
// AbortError-named DOMException so api.ts recognizes the cancellation. kea-loaders reduces a
// rejection to its message, so failure reducers and listeners see only this text.
export const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const
export const UNMOUNTING_ERROR_MESSAGE = 'unmounting component' as const

// Neither of our abort reasons contains "abort", so both need matching by name: an unmatched
// one is treated as a genuine failure, which toasts the user, fires a query-failed capture,
// or drops a loading flag for a request that was cancelled on purpose.
export function isUserInitiatedError(error: unknown): boolean {
    const errorStr = String(error).toLowerCase()
    return error === NEW_QUERY_STARTED_ERROR_MESSAGE || error === UNMOUNTING_ERROR_MESSAGE || errorStr.includes('abort')
}

type LoadingHandlers = Record<string, (state: boolean, payload: { error: string }) => boolean>

/**
 * Handlers for a loading flag whose in-flight request can be aborted by a superseding call.
 *
 * kea-loaders' auto `<key>Loading` drops to false when the aborted request's rejection lands
 * as a failure, even though the superseding call is still in flight, so the UI flashes its
 * empty state between the spinner and the data. These handlers ride out user-initiated aborts
 * and only clear on success or a real failure. Pass every loader action that should drive
 * the flag (e.g. a first-page and a next-page fetch), and keep the reducer's `[false as
 * boolean, ...]` default inline, where kea-typegen can read it.
 */
export function abortResilientLoading(...loaderActions: string[]): LoadingHandlers {
    const handlers: LoadingHandlers = {}
    for (const action of loaderActions) {
        handlers[action] = () => true
        handlers[`${action}Success`] = () => false
        handlers[`${action}Failure`] = (state, { error }) => (isUserInitiatedError(error) ? state : false)
    }
    return handlers
}
