import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Suspense } from 'react'

import { LemonTabs, SpinnerOverlay } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAppContext } from 'lib/utils/getAppContext'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AlertType } from '../types'
import { AlertsTab, getActiveAlertsTab, getAlertsTabs } from '../utils'

const InsightAlerts = lazyWithRetry(() =>
    import('./InsightAlerts').then((module) => ({
        default: module.InsightAlerts,
    }))
)

const LogsAlertingSection = lazyWithRetry(() =>
    import('products/logs/frontend/components/LogsAlerting/LogsAlertingSection').then((module) => ({
        default: module.LogsAlertingSection,
    }))
)

interface AlertsProps {
    alertId: AlertType['id'] | null
}

function hasEffectiveResourceAccess(resourceType: AccessControlResourceType): boolean {
    return getAppContext()?.effective_resource_access_control?.[resourceType] !== AccessControlLevel.None
}

export function Alerts({ alertId }: AlertsProps): JSX.Element {
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const showLogAlerts = useFeatureFlag('LOGS_ALERTING')
    const canViewInsightAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Insight)
    const canViewLogAlerts = showLogAlerts && hasEffectiveResourceAccess(AccessControlResourceType.Logs)

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
            <LemonTabs<AlertsTab> activeKey={activeTab} onChange={switchTab} tabs={tabs} sceneInset />
            <Suspense fallback={<SpinnerOverlay />}>
                {activeTab === AlertsTab.LOGS ? <LogsAlertingSection /> : <InsightAlerts alertId={alertId} />}
            </Suspense>
        </>
    )
}
