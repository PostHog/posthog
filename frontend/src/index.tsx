import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { AppWrapper } from 'scenes/App'
import { initKea } from './initKea'

import { loadPostHogJS } from './loadPostHogJS'
import { GlobalStyles } from './GlobalStyles'

loadPostHogJS()
initKea()

ReactDOM.render(
    <Provider store={getContext().store}>
        <GlobalStyles />
        <AppWrapper />
    </Provider>,
    document.getElementById('root')
)
