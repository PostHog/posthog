import React from 'react'
import { Dashboard } from '~/scenes/dashboard/Dashboard'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import './SharedDashboard.scss'
import { DashboardPlacement } from '~/types'
import { ExportedData, ExportType } from '~/exporter/types'

interface SharedDashboardProps {
    exportedData: ExportedData
}

export function SharedDashboard({
    exportedData: { type, whitelabel, team, dashboard },
}: SharedDashboardProps): JSX.Element {
    if (!dashboard) {
        return <div>Error</div>
    }
    return (
        <div className="SharedDashboard">
            {!whitelabel ? (
                type !== ExportType.Embed ? (
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
                        <span className="SharedDashboard-header-team">{team?.name}</span>
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

            <Dashboard
                id={String(dashboard.id)}
                shareToken={dashboard.share_token}
                placement={DashboardPlacement.Public}
            />

            {!whitelabel && (
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
    )
}
