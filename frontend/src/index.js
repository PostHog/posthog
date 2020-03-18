import './style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { resetContext, getContext } from 'kea'
import listenersPlugin from 'kea-listeners'
import { routerPlugin } from 'kea-router'

import App from './scenes/App'

resetContext({
    createStore: {
        // additional options (e.g. middleware, reducers, ...)
    },
    plugins: [routerPlugin, listenersPlugin],
})

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)
