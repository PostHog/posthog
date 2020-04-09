import './style.scss'
import 'antd/dist/antd.css';
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { resetContext, getContext } from 'kea'
import listenersPlugin from 'kea-listeners'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'

import App from './scenes/App'
import { toast } from 'react-toastify'

resetContext({
    createStore: {
        // additional options (e.g. middleware, reducers, ...)
    },
    plugins: [
        routerPlugin,
        loadersPlugin({
            onError({ error, reducerKey, actionKey, logic }) {
                toast.error(
                    <div>
                        <h1>Error loading "{reducerKey}".</h1>
                        <p className="info">Action "{actionKey}" responded with</p>
                        <p className="error-message">"{error.message}"</p>
                    </div>
                )
                window.Sentry && window.Sentry.captureException(error)
            },
        }),
        listenersPlugin,
    ],
})

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)
