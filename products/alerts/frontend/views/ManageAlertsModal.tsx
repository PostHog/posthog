import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { AlertStateIndicator } from '../components/AlertDefinition'
import { buildAlertSummary } from '../components/alertSummary'
import { AlertSummaryBanner } from '../components/AlertSummaryBanner'
import { InsightAlertsLogicProps, alertsUnsupportedReason, insightAlertsLogic } from '../logic/insightAlertsLogic'
import { AlertType } from '../types'

interface AlertListItemProps {
    alert: AlertType
    destinationCount?: number
    destinationsLoading?: boolean
    onClick: () => void
}

export function AlertListItem({
    alert,
    destinationCount = 0,
    destinationsLoading = false,
    onClick,
}: AlertListItemProps): JSX.Element {
    const summary = buildAlertSummary(alert, alert.subscribed_users?.length ?? 0, destinationCount)
    if (destinationsLoading) {
        summary.notifies = 'Loading…'
    }

    return (
        <LemonButton onClick={onClick} data-attr="alert-list-item" fullWidth>
            <AlertSummaryBanner
                summary={summary}
                header={
                    <div className="flex items-center justify-between gap-3">
                        <span className="min-w-0 truncate">{alert.name}</span>
                        <AlertStateIndicator alert={alert} />
                    </div>
                }
                footer={<UserActivityIndicator prefix="Created" at={alert.created_at} by={alert.created_by} />}
            />
        </LemonButton>
    )
}

interface ManageAlertsModalProps extends InsightAlertsLogicProps {
    isOpen: boolean
    insightShortId: InsightShortId
    canCreateAlertForInsight: boolean
    /** The insight's query, so the unsupported-reason copy can be specific (e.g. time-to-convert funnels). */
    insightQuery?: Record<string, any> | null
    onClose?: () => void
    onCreateAlert?: () => void
    onEditAlert?: (alertId: AlertType['id']) => void
}

export function ManageAlertsModal(props: ManageAlertsModalProps): JSX.Element {
    const { push } = useActions(router)
    const logic = insightAlertsLogic(props)

    const { alerts, alertsLoading, alertDestinationCounts, alertDestinationCountsLoading } = useValues(logic)

    const showDeferredListSpinner = props.deferInitialAlertsLoad && props.isOpen && alertsLoading
    const openAlert = (alertId: AlertType['id']): void => {
        if (props.onEditAlert) {
            props.onClose?.()
            props.onEditAlert(alertId)
            return
        }

        push(urls.insightAlert(props.insightShortId, alertId))
    }
    const createAlert = (): void => {
        if (props.onCreateAlert) {
            props.onClose?.()
            props.onCreateAlert()
            return
        }

        push(urls.insightAlert(props.insightShortId, 'new'))
    }

    return (
        <LemonModal onClose={props.onClose} isOpen={props.isOpen} width={600} simple title="">
            <LemonModal.Header>
                <h3 className="!m-0">Manage Alerts</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                <div className="mb-4">
                    With alerts, PostHog monitors your insight at a recurring interval and notifies you when conditions
                    are met.
                    <br />
                    <Link to={urls.alerts()} target="_blank">
                        View all your alerts here
                    </Link>
                </div>

                {showDeferredListSpinner ? (
                    <div className="flex justify-center p-8">
                        <Spinner />
                    </div>
                ) : alerts.length ? (
                    <div className="deprecated-space-y-2">
                        <div>
                            <strong>{alerts?.length}</strong> {pluralize(alerts.length || 0, 'alert', 'alerts', false)}
                        </div>

                        {alerts.map((alert) => (
                            <AlertListItem
                                key={alert.id}
                                alert={alert}
                                destinationCount={alertDestinationCounts[alert.id] ?? 0}
                                destinationsLoading={alertDestinationCountsLoading}
                                onClick={() => openAlert(alert.id)}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="flex flex-col p-4 items-center text-center">
                        <h3>There are no alerts for this insight</h3>

                        <p>Once alerts are created they will display here. </p>
                    </div>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={props.onClose}>
                    Close
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={createAlert}
                    disabledReason={
                        !props.canCreateAlertForInsight ? alertsUnsupportedReason({}, props.insightQuery) : undefined
                    }
                >
                    New alert
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
