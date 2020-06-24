import './../../style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'

initKea()

ReactDOM.render(
    <Provider store={getContext().store}>
        <Dashboard id={267} public_token="blabla" />
    </Provider>,
    document.getElementById('root')
)
