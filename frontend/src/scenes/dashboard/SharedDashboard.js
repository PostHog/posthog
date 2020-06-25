import './../../style.scss'
import 'scenes/dashboard/DashboardItems.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'

initKea()

ReactDOM.render(
    <Provider store={getContext().store}>
        <div style={{ background: 'var(--gray-background)' }}>
            <Dashboard id={267} public_token="blabla" />
        </div>
    </Provider>,
    document.getElementById('root')
)
