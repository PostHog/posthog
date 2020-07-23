import './../../style.scss'
import './DashboardItems.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'

import PostHogLogo from './../../../public/posthog-logo.svg'
import { Col, Row } from 'antd'

initKea()

let dashboard = window.__SHARED_DASHBOARD__
ReactDOM.render(
    <Provider store={getContext().store}>
        <div style={{ background: 'var(--gray-background)', minHeight: '100vh', top: 0 }}>
            <Row style={{ marginBottom: '1rem' }}>
                <Col sm={7} xs={24} style={{ padding: '1rem' }}>
                    <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">
                        <img src={PostHogLogo} style={{ height: '2rem', marginTop: 4 }} />
                    </a>
                </Col>
                <Col sm={10} xs={24} style={{ padding: '1rem' }}>
                    <h1 style={{ textAlign: 'center' }}>{dashboard.name}</h1>
                </Col>
                <Col sm={7} xs={0} style={{ padding: '1rem', textAlign: 'right' }}>
                    <span style={{ paddingTop: 15, display: 'inline-block' }}>{dashboard.team_name}</span>
                </Col>
            </Row>
            <Dashboard id={dashboard.id} shareToken={dashboard.share_token} />

            <div style={{ textAlign: 'center', paddingBottom: '4rem', marginTop: '1rem' }}>
                Made with <a href="https://posthog.com">PostHog - Open Source Product Analytics</a>
            </div>
        </div>
    </Provider>,
    document.getElementById('root')
)
