import '~/style/style.scss' /* Contains PostHog's main styling configurations */
import '~/style/antd.less' /* Imports Ant Design's components */
import './style.scss' /* DEPRECATED */
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { App } from 'scenes/App'
import { initKea } from './initKea'

initKea()

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)
