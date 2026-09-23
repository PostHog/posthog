import { useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { urls } from 'scenes/urls'

import { AlertState } from '~/queries/schema/schema-general'
import { SavedInsightsTabs } from '~/types'

import { alertsLogic } from 'products/alerts/frontend/logic/alertsLogic'
import { AlertType } from 'products/alerts/frontend/types'

import { AlertRow } from './AlertRow'

export function FiringAlerts(): JSX.Element {
    const { alerts, alertsResponseLoading } = useValues(alertsLogic)
    const firingAlerts = alerts.filter((alert) => alert.state === AlertState.FIRING && alert.enabled)

    return (
        <CompactList
            title="Firing alerts"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.Alerts)}
            viewAllDataAttr="insights-home-tab-firing-alerts-view-all"
            loading={alertsResponseLoading}
            emptyMessage={{
                title: 'No alerts are firing',
                description: 'PostHog will show active alerts here.',
                buttonText: 'View all alerts',
                buttonTo: urls.savedInsights(SavedInsightsTabs.Alerts),
                buttonDataAttr: 'firing-alerts-empty-view-all',
            }}
            items={firingAlerts.slice(0, 5)}
            renderRow={(alert: AlertType) => <AlertRow key={alert.id} alert={alert} />}
            contentHeightBehavior="fit-content"
        />
    )
}
