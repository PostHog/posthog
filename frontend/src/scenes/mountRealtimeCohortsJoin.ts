import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { retryImport } from 'lib/utils/retryImport'

/** Mounts the logic that joins the project to the realtime cohorts beta. Returns the unmount. */
export function mountRealtimeCohortsJoin(): () => void {
    let disposed = false
    let unmountLogic: (() => void) | undefined
    // A dynamic import, because the shell may not import a product's code statically.
    void retryImport(() => import('products/cohorts/frontend/realtime/realtimeCohortsJoinLogic'))
        .then(({ realtimeCohortsJoinLogic }) => {
            if (!disposed) {
                unmountLogic = realtimeCohortsJoinLogic.mount()
            }
        })
        .catch((error) => {
            // A chunk that failed to load leaves the join to the next page load.
            if (!isChunkLoadError(error)) {
                throw error
            }
        })
    return () => {
        disposed = true
        unmountLogic?.()
    }
}
