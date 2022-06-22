import '~/styles'
import './Exporter.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { loadPostHogJS } from '~/loadPostHogJS'
import { initKea } from '~/initKea'
import { ExportedData, ExportType } from '~/exporter/types'
import { DashboardPlacement } from '~/types'
import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import { Dashboard } from 'scenes/dashboard/Dashboard'

const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA

if (exportedData.type === ExportType.Image) {
    // Disable tracking for screenshot captures
    window.JS_POSTHOG_API_KEY = null
}

loadPostHogJS()
initKea()

function Exporter(): JSX.Element {
    const { type, dashboard, insight, whitelabel, team } = exportedData

    return (
        <div className="Exporter">
            {!whitelabel && dashboard ? (
                type === ExportType.Scene ? (
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
                ) : type === ExportType.Embed ? (
                    <a
                        href="https://posthog.com"
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ display: 'block', marginBottom: '-2.5rem' }}
                    >
                        <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                    </a>
                ) : type === ExportType.Image ? (
                    <>
                        <h1 className="mb-05">{dashboard.name}</h1>
                        <p>{dashboard.description}</p>
                    </>
                ) : null
            ) : null}

            {insight ? (
                <ExportedInsight insight={insight} showLogo={!whitelabel} />
            ) : dashboard ? (
                <Dashboard
                    id={String(dashboard.id)}
                    shareToken={dashboard.share_token}
                    placement={type === ExportType.Image ? DashboardPlacement.Export : DashboardPlacement.Public}
                />
            ) : (
                <h1 className="text-center pa">Something went wrong...</h1>
            )}

            {!whitelabel && dashboard && (
                <div className="text-center pb ma">
                    {type === ExportType.Image ? <FriendlyLogo style={{ fontSize: '1.125rem' }} /> : null}
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

ReactDOM.render(<Exporter />, document.getElementById('root'))
