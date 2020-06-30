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
        <div style={{ background: 'var(--gray-background)', minHeight: '100vh', top: 0, padding: '2rem' }}>
            <div>
                <h1 style={{ display: 'inline-block' }}>{dashboard.name}</h1>
                <h1 style={{ float: 'right' }}>{dashboard.team_name}</h1>
            </div>
            <Dashboard id={dashboard.id} share_token={dashboard.share_token} />

            <div style={{ textAlign: 'center' }}>
                Made with <a href="https://posthog.com">PostHog - Open Source Product Analytics</a>
            </div>
        </div>
    </Provider>,
    document.getElementById('root')
)
