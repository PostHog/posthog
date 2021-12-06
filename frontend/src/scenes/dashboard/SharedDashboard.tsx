import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'
import { initKea } from '~/initKea'
import { Dashboard } from './Dashboard'
import { Col, Row } from 'antd'
import { loadPostHogJS } from '~/loadPostHogJS'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import '~/styles'
import './DashboardItems.scss'

loadPostHogJS()
initKea()

const dashboard = (window as any).__SHARED_DASHBOARD__
const isEmbedded = window.location.search.includes('embedded')

ReactDOM.render(
    <Provider store={getContext().store}>
        <div style={{ minHeight: '100vh', top: 0, padding: !isEmbedded ? '1rem' : '0.5rem 1rem' }}>
            {!isEmbedded ? (
                <Row align="middle">
                    <Col sm={7} xs={24}>
                        <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">
                            <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                        </a>
                    </Col>
                    <Col sm={10} xs={24} style={{ textAlign: 'center' }}>
                        <>
                            <h1 style={{ marginBottom: '0.25rem', fontWeight: 600 }} data-attr="dashboard-item-title">
                                {dashboard.name}
                            </h1>
                            <span>{dashboard.description}</span>
                        </>
                    </Col>
                    <Col sm={7} xs={0} style={{ textAlign: 'right' }}>
                        <span style={{ display: 'inline-block' }}>{dashboard.team_name}</span>
                    </Col>
                </Row>
            ) : (
                <a
                    href="https://posthog.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ display: 'block', marginBottom: '-3rem' }}
                >
                    <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                </a>
            )}

            <Dashboard id={dashboard.id} shareToken={dashboard.share_token} />

            <div style={{ textAlign: 'center', paddingBottom: '1rem' }}>
                Made with{' '}
                <a
                    href="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                    target="_blank"
                    rel="noopener"
                >
                    PostHog – open-source product analytics
                </a>
            </div>
        </div>
    </Provider>,
    document.getElementById('root')
)
