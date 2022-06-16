import React from 'react'
import { Dashboard } from '~/scenes/dashboard/Dashboard'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import { DashboardPlacement } from '~/types'
import { ExportedInsight } from './ExportedInsight/ExportedInsight'
import { ExportedData } from '~/exporter/types'

interface ExportViewerProps {
    exportedData: ExportedData
}

export function ExportViewer({ exportedData: { dashboard, insight, whitelabel } }: ExportViewerProps): JSX.Element {
    return (
        <div className="pa" style={{ minHeight: '100vh' }}>
            {!whitelabel && dashboard && (
                <>
                    <h1 className="mb-05">{dashboard.name}</h1>
                    <p>{dashboard.description}</p>
                </>
            )}

            {insight ? (
                <div>
                    <ExportedInsight insight={insight} showLogo={!whitelabel} />
                </div>
            ) : dashboard ? (
                <Dashboard
                    id={dashboard.id?.toString()}
                    shareToken={dashboard?.share_token}
                    placement={DashboardPlacement.Export}
                />
            ) : (
                <h1 className="text-center pa">Something went wrong...</h1>
            )}

            {!whitelabel && dashboard && (
                <div className="text-center pb ma">
                    <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                    <div>
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
            )}
        </div>
    )
}
