import { useValues } from 'kea'

import { alertsLogic } from 'lib/components/Alerts/alertsLogic'
import { AlertType } from 'lib/components/Alerts/types'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { AlertState } from '~/queries/schema/schema-general'
import { SavedInsightsTabs } from '~/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'

interface AlertRowProps {
    alert: AlertType
}

function AlertRow({ alert }: AlertRowProps): JSX.Element {
    return (
        <ProjectHomePageCompactListItem
            title={alert.name}
            subtitle={
                alert.last_checked_at ? (
                    <>
                        Last checked <TZLabel time={alert.last_checked_at} />
                    </>
                ) : (
                    'Not yet checked'
                )
            }
            to={urls.alert(alert.id)}
            dataAttr="firing-alert-item"
        />
    )
}

export function FiringAlerts(): JSX.Element {
    const { alerts, alertsLoading } = useValues(alertsLogic)

    const firingAlerts = alerts.filter((alert) => alert.state === AlertState.FIRING && alert.enabled)

    return (
        <CompactList
            title="Firing alerts"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.Alerts)}
            loading={alertsLoading}
            emptyMessage={{
                title: 'All good!',
                description: 'No alerts are currently firing.',
                buttonText: 'View all alerts',
                buttonTo: urls.savedInsights(SavedInsightsTabs.Alerts),
            }}
            items={firingAlerts.slice(0, 5)}
            renderRow={(alert: AlertType) => <AlertRow key={alert.id} alert={alert} />}
            contentHeightBehavior="fit-content"
        />
    )
}
