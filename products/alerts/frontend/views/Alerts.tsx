import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAppContext } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LogsAlertingSection } from 'products/logs/frontend/components/LogsAlerting/LogsAlertingSection'

import { AlertType } from '../types'
import { AlertsTab, getActiveAlertsTab, getAlertsTabs } from '../utils'
import { InsightAlerts } from './InsightAlerts'

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
            <SceneTitleSection
                name="Alerts"
                description={ALERTS_DESCRIPTION[activeTab]}
                resourceType={{ type: 'inbox' }}
            />
            <LemonTabs<AlertsTab> activeKey={activeTab} onChange={switchTab} tabs={tabs} sceneInset />
            {activeTab === AlertsTab.LOGS ? <LogsAlertingSection /> : <InsightAlerts alertId={alertId} />}
        </>
    )
}
