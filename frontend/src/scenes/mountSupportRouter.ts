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
 * `mounted` is returned so tests can observe both paths; App leaves it floating.
 */
export function mountSupportRouter(): { unmount: () => void; mounted: Promise<void> } {
    let unmountRouter: (() => void) | undefined
    const mounted = retryImport(() => import('lib/components/Support/supportRouterLogic'))
        .then(({ supportRouterLogic }) => {
            unmountRouter = supportRouterLogic.mount()
        })
        .catch((error) => {
            if (!isChunkLoadError(error)) {
                throw error
            }
            console.warn('[App] Support router chunk failed to load; #panel=support is inactive', error)
        })
    return { unmount: () => unmountRouter?.(), mounted }
}
