import { resetContext } from 'kea'
import localStoragePlugin from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import { windowValuesPlugin } from 'kea-window-values'
import { toast } from 'react-toastify'
import React from 'react'

export const initKea = () =>
    resetContext({
        plugins: [
            localStoragePlugin,
            windowValuesPlugin({ window: window }),
            routerPlugin,
            loadersPlugin({
                onFailure({ error, reducerKey, actionKey }) {
                    toast.error(
                        <div>
                            <h1>Error loading "{reducerKey}".</h1>
                            <p className="info">Action "{actionKey}" responded with</p>
                            <p className="error-message">"{error.message}"</p>
                        </div>
                    )
                    window.Sentry ? window.Sentry.captureException(error) : console.error(error)
                },
            }),
        ],
    })
