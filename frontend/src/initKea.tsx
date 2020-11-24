import { resetContext } from 'kea'
import localStoragePlugin from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import { windowValuesPlugin } from 'kea-window-values'
import { toast } from 'react-toastify'
import React from 'react'
import { identifierToHuman } from 'lib/utils'

export function initKea(): void {
    resetContext({
        plugins: [
            localStoragePlugin,
            windowValuesPlugin({ window: window }),
            routerPlugin,
            loadersPlugin({
                onFailure({ error, reducerKey, actionKey }) {
                    toast.error(
                        <div>
                            <h1>Error on {identifierToHuman(reducerKey)}</h1>
                            <p>
                                Attempting to {identifierToHuman(actionKey, false)} returned an error:{' '}
                                <span className="error-details">{error.detail || 'Unknown exception.'}</span>
                            </p>
                        </div>
                    )
                    window['Sentry'] ? window['Sentry'].captureException(error) : console.error(error)
                },
            }),
        ],
    })
}
