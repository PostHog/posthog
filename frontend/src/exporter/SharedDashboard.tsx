import React from 'react'
import { Dashboard } from '~/scenes/dashboard/Dashboard'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import '~/styles'
import './SharedDashboard.scss'
import { DashboardPlacement, AvailableFeature, DashboardType, TeamType } from '~/types'

interface SharedDashboardProps {
    dashboard: Partial<DashboardType>
    team: Partial<TeamType>
    availableFeatures: AvailableFeature[]
}

export function SharedDashboard({ team, dashboard, availableFeatures }: SharedDashboardProps): JSX.Element {
    const isEmbedded = window.location.search.includes('embedded')
    const whiteLabel =
        window.location.search.includes('whitelabel') && availableFeatures.includes(AvailableFeature.WHITE_LABELLING)

    return (
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
                        <span className="SharedDashboard-header-team">{team.name}</span>
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
    )
}
