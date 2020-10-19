import './style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import App from './scenes/App'
import { initKea } from './initKea'

initKea()
console.log('snowpacking!')

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)

// Hot Module Replacement (HMR) - Remove this snippet to remove HMR.
// Learn more: https://www.snowpack.dev/#hot-module-replacement
if (import.meta.hot) {
    import.meta.hot.accept()
}
