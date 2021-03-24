import { resetContext } from 'kea'
import localStoragePlugin from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import { windowValuesPlugin } from 'kea-window-values'
import { errorToast, identifierToHuman } from 'lib/utils'

export function initKea(): void {
    resetContext({
        plugins: [
            localStoragePlugin,
            windowValuesPlugin({ window: window }),
            routerPlugin,
            loadersPlugin({
                onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                    // Toast if it's a fetch error or a specific API update error
                    console.log(error)
                    if (
                        error?.message === 'Failed to fetch' ||
                        (error?.status && ![0, 200, 201, 204].includes(error?.status))
                    ) {
                        errorToast(
                            `Error on ${identifierToHuman(reducerKey)}`,
                            `Attempting to ${identifierToHuman(actionKey).toLowerCase()} returned an error:`,
                            error.detail,
                            error.code
                        )
                    }
                    console.error(error)
                    ;(window as any).Sentry?.captureException(error)
                },
            }),
        ],
    })
}
