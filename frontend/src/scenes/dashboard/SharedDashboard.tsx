import '~/styles'
import './DashboardItems.scss'

import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'

import PostHogLogo from 'public/posthog-logo.svg'
import { Col, Row } from 'antd'
import { loadPostHogJS } from '~/loadPostHogJS'

loadPostHogJS()
initKea()

const dashboard = (window as any).__SHARED_DASHBOARD__
ReactDOM.render(
    <Provider store={getContext().store}>
        <div style={{ minHeight: '100vh', top: 0 }}>
            <Row>
                <Col sm={7} xs={24} style={{ padding: '1rem' }}>
                    <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">
                        <img src={PostHogLogo} style={{ height: '2rem', marginTop: 4 }} />
                    </a>
                </Col>
                <Col sm={10} xs={24} style={{ padding: '1rem' }}>
                    <h1 style={{ textAlign: 'center' }} data-attr="dashboard-item-title">
                        {dashboard.name}
                    </h1>
                </Col>
                <Col sm={7} xs={0} style={{ padding: '1rem', textAlign: 'right' }}>
                    <span style={{ paddingTop: 15, display: 'inline-block' }}>{dashboard.team_name}</span>
                </Col>
            </Row>
            <p style={{ textAlign: 'center', marginBottom: '1rem' }}>{dashboard.description}</p>

            <div style={{ margin: '0 1rem' }}>
                <Dashboard id={dashboard.id} shareToken={dashboard.share_token} />
            </div>

            <div style={{ textAlign: 'center', paddingBottom: '4rem', marginTop: '1rem' }}>
                Made with{' '}
                <a
                    href="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                    target="_blank"
                    rel="noopener"
                >
                    PostHog - Open Source Product Analytics
                </a>
            </div>
        </div>
    </Provider>,
    document.getElementById('root')
)
