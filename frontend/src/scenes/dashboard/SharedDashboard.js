import './../../style.scss'
import './DashboardItems.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'

initKea()

let dashboard = window.__SHARED_DASHBOARD__
ReactDOM.render(
    <Provider store={getContext().store}>
        <div style={{ background: 'var(--gray-background)' }}>
            <Dashboard id={dashboard.id} share_token={dashboard.share_token} />
        </div>
    </Provider>,
    document.getElementById('root')
)
