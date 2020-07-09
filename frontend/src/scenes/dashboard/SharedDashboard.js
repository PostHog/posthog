import './../../style.scss'
import './DashboardItems.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'

import PostHogLogo from './../../../public/posthog-logo.svg'

initKea()

let dashboard = window.__SHARED_DASHBOARD__
ReactDOM.render(
    <Provider store={getContext().store}>
        <div style={{ background: 'var(--gray-background)', minHeight: '100vh', top: 0, padding: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">
                    <img src={PostHogLogo} style={{ height: '2rem', marginTop: 4 }} />
                </a>
                <h1 style={{ display: 'inline-block' }}>{dashboard.name}</h1>
                <span style={{ marginTop: 15 }}>{dashboard.team_name}</span>
            </div>
            <Dashboard id={dashboard.id} share_token={dashboard.share_token} />

            <div style={{ textAlign: 'center' }}>
                Made with <a href="https://posthog.com">PostHog - Open Source Product Analytics</a>
            </div>
        </div>
    </Provider>,
    document.getElementById('root')
)
