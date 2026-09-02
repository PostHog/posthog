import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Suspense, useEffect } from 'react'

import { LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { getAppContext } from 'lib/utils/getAppContext'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AlertType } from '../types'
import { AlertsTab, getActiveAlertsTab, getAlertsTabs } from '../utils'

const loadInsightAlerts = (): Promise<{ default: typeof import('./InsightAlerts').InsightAlerts }> =>
    import('./InsightAlerts').then((module) => ({ default: module.InsightAlerts }))
const loadLogsAlertingSection = (): Promise<{
    default: typeof import('products/logs/frontend/components/LogsAlerting/LogsAlertingSection').LogsAlertingSection
}> =>
    import('products/logs/frontend/components/LogsAlerting/LogsAlertingSection').then((module) => ({
        default: module.LogsAlertingSection,
    }))

const InsightAlerts = lazyWithRetry(loadInsightAlerts)
const LogsAlertingSection = lazyWithRetry(loadLogsAlertingSection)

interface AlertsProps {
    alertId: AlertType['id'] | null
}

const ALERTS_DESCRIPTION: Record<AlertsTab, string> = {
    [AlertsTab.INSIGHTS]: 'Monitor insight metrics and get notified when conditions are met.',
    [AlertsTab.LOGS]: 'Monitor matching logs and get notified when they cross a threshold.',
}

function hasEffectiveResourceAccess(resourceType: AccessControlResourceType): boolean {
    return getAppContext()?.effective_resource_access_control?.[resourceType] !== AccessControlLevel.None
}

function AlertsPanelSkeleton(): JSX.Element {
    return (
        <div className="space-y-4 p-4">
            <LemonSkeleton className="h-10 w-full" />
            <LemonSkeleton className="h-32 w-full" />
            <LemonSkeleton className="h-32 w-full" />
        </div>
    )
}

export function Alerts({ alertId }: AlertsProps): JSX.Element {
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const canViewInsightAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Insight)
    const canViewLogAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Logs)

    useEffect(() => {
        void loadInsightAlerts()
        void loadLogsAlertingSection()
    }, [])

    const activeTab = getActiveAlertsTab({
        alertId,
        requestedTab: typeof searchParams.alert_type === 'string' ? searchParams.alert_type : undefined,
        canViewInsightAlerts,
        canViewLogAlerts,
    })

    if (activeTab === null) {
        return <AccessDenied />
    }

    const tabs = getAlertsTabs({ canViewInsightAlerts, canViewLogAlerts })

    const switchTab = (tab: AlertsTab): void => {
        const nextSearchParams = { ...searchParams }
        delete nextSearchParams.alert_id
        nextSearchParams.alert_type = tab
        push(urls.alerts(), nextSearchParams)
    }

    return (
        <>
            <SceneTitleSection
                name="Alerts"
                description={ALERTS_DESCRIPTION[activeTab]}
                resourceType={{ type: 'inbox' }}
            />
            <LemonTabs<AlertsTab> activeKey={activeTab} onChange={switchTab} tabs={tabs} sceneInset />
            <Suspense fallback={<AlertsPanelSkeleton />}>
                {activeTab === AlertsTab.LOGS ? <LogsAlertingSection /> : <InsightAlerts alertId={alertId} />}
            </Suspense>
        </>
    )
}
