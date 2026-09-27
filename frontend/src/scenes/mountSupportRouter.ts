import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { retryImport } from 'lib/utils/retryImport'

/**
 * Mounts the support-hash router (handles #panel=support) and returns how to unmount it.
 *
 * The import floats in an effect, so no boundary sits above it and an exhausted retry becomes an
 * unhandled rejection. A stale chunk costs only #panel=support and the next page load fetches the
 * current chunk, so a chunk-load failure degrades here rather than reloading the page under the
 * user. Any other error is a real bug and still propagates.
 *
 * The import can also outlive the caller. If the caller unmounts before it resolves,
 * do not mount the router, because mounting can process the current URL.
 *
 * `mounted` is returned so tests can observe both paths; App leaves it floating.
 */
export function mountSupportRouter(): { unmount: () => void; mounted: Promise<void> } {
    let disposed = false
    let unmountRouter: (() => void) | undefined
    const mounted = retryImport(() => import('lib/components/Support/supportRouterLogic'))
        .then(({ supportRouterLogic }) => {
            if (disposed) {
                return
            }
            unmountRouter = supportRouterLogic.mount()
        })
        .catch((error) => {
            if (!isChunkLoadError(error)) {
                throw error
            }
            console.warn('[App] Support router chunk failed to load; #panel=support is inactive', error)
        })
    return {
        unmount: () => {
            disposed = true
            unmountRouter?.()
            unmountRouter = undefined
        },
        mounted,
    }
}
