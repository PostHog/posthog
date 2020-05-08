import './style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { resetContext, getContext } from 'kea'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import NProgress from 'nprogress'

import App from './scenes/App'
import { toast } from 'react-toastify'

let loadingCounter = 0
let loadingTimeout

const startLoading = () => {
    loadingTimeout = window.setTimeout(() => NProgress.start(), 500)
}

const stopLoading = () => {
    window.clearTimeout(loadingTimeout)
    NProgress.done()
}

resetContext({
    plugins: [
        routerPlugin,
        loadersPlugin({
            onStart() {
                loadingCounter++ === 0 && startLoading()
            },
            onSuccess() {
                --loadingCounter === 0 && stopLoading()
            },
            onFailure({ error, reducerKey, actionKey, logic }) {
                --loadingCounter === 0 && stopLoading()
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
    ],
})

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)
