import React from 'react'
import ReactDOM from 'react-dom'
import { initKea } from '~/initKea'
import { Dashboard } from '~/scenes/dashboard/Dashboard'
import { loadPostHogJS } from '~/loadPostHogJS'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import '~/styles'
import './SharedDashboard.scss'
import { DashboardPlacement, AvailableFeature } from '~/types'

loadPostHogJS()
initKea()

const dashboard = (window as any).__SHARED_DASHBOARD__
const isEmbedded = window.location.search.includes('embedded')
const whiteLabel =
    window.location.search.includes('whitelabel') &&
    dashboard.available_features.includes(AvailableFeature.WHITE_LABELLING)

ReactDOM.render(
    <>
        <div className="SharedDashboard">
            {!whiteLabel ? (
                !isEmbedded ? (
                    <div className="SharedDashboard-header">
                        <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">
                            <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                        </a>
                        <div className="SharedDashboard-header-title">
                            <h1 className="mb-05" data-attr="dashboard-item-title">
                                {dashboard.name}
                            </h1>
                            <span>{dashboard.description}</span>
                        </div>
                        <span className="SharedDashboard-header-team">{dashboard.team_name}</span>
                    </div>
                ) : (
                    <a
                        href="https://posthog.com"
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ display: 'block', marginBottom: '-2.5rem' }}
                    >
                        <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                    </a>
                )
            ) : null}

            <Dashboard id={dashboard.id} shareToken={dashboard.share_token} placement={DashboardPlacement.Public} />

            {!whiteLabel && (
                <div className="text-center pb">
                    Made with{' '}
                    <a
                        href="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                        target="_blank"
                        rel="noopener"
                    >
                        PostHog – open-source product analytics
                    </a>
                </div>
            )}
        </div>
    </>,
    document.getElementById('root')
)
