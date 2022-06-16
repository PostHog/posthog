import React, { useEffect } from 'react'
import { Dashboard } from '~/scenes/dashboard/Dashboard'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import { DashboardPlacement, DashboardType } from '~/types'
import { useActions } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { ExportedInsight } from './ExportedInsight/ExportedInsight'
import { ExportedData } from '~/exporter/types'

interface ExportViewerProps {
    exportedData: ExportedData
}

export function ExportViewer({ exportedData }: ExportViewerProps): JSX.Element {
    const searchParams = new URLSearchParams(window.location.search)
    const hideDetails = searchParams.get('hide_details') === 'true'

    const { dashboard, insight } = exportedData

    const modelLogic = dashboardsModel({ id: dashboard?.id })
    const logic = dashboardLogic({ id: dashboard?.id })

    const modelActions = useActions(modelLogic)
    const actions = useActions(logic)

    useEffect(() => {
        if (dashboard) {
            // NOTE: We are inflating the logic with our pre-loaded data. This may or may not be a good idea...
            modelActions.loadDashboardsSuccess([dashboard])
            actions.loadDashboardItemsSuccess(dashboard as DashboardType)
            actions.setReceivedErrorsFromAPI(false)
        }
    }, [dashboard])

    const content = insight ? (
        <div>
            <ExportedInsight insight={insight} showLogo={!hideDetails} />
        </div>
    ) : dashboard ? (
        <Dashboard id={dashboard.id?.toString()} placement={DashboardPlacement.Export} />
    ) : (
        <h1 className="text-center pa">Something went wrong...</h1>
    )

    return (
        <div className="pa" style={{ minHeight: '100vh' }}>
            {!hideDetails && dashboard && (
                <>
                    <h1 className="mb-05">{dashboard.name}</h1>
                    <p>{dashboard.description}</p>
                </>
            )}

            {content}

            {!hideDetails && dashboard && (
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
