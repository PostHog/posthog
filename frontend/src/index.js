import './style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { resetContext, getContext } from 'kea'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'

import App from './scenes/App'
import { toast } from 'react-toastify'

resetContext({
    plugins: [
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

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)
