import { resetContext } from 'kea'
import localStoragePlugin from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import { windowValuesPlugin } from 'kea-window-values'

export function initKea(): void {
    resetContext({
        plugins: [
            localStoragePlugin,
            windowValuesPlugin({ window: window }),
            routerPlugin,
            loadersPlugin({
                onFailure({ error }: { error: any }) {
                    if ((window as any).Sentry) {
                        ;(window as any).Sentry.captureException(error)
                    } else {
                        console.error(error)
                    }
                },
            }),
        ],
    })
}
