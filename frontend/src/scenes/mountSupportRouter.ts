import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { retryImport } from 'lib/utils/retryImport'

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
