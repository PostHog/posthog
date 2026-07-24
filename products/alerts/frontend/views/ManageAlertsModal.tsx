import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { InsightThresholdType } from '~/queries/schema/schema-general'
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
    redesigned: boolean
}

function AlertSummary({ alert }: { alert: AlertType }): JSX.Element | null {
    if (!alert.enabled) {
        return <div className="text-secondary pl-3">Disabled</div>
    }

    if (alert.detector_config) {
        const config = alert.detector_config as unknown as Record<string, unknown>
        if (config.type === 'ensemble') {
            const detectors = (config.detectors as Array<{ type: string }>) ?? []
            const operator = (config.operator as string)?.toUpperCase() ?? 'AND'
            const labels = detectors.map((d) => (d.type === 'zscore' ? 'Z-Score' : d.type === 'mad' ? 'MAD' : d.type))
            return <div className="text-secondary pl-3">{labels.join(` ${operator} `)}</div>
        }
        const { type, threshold } = config as { type: string; threshold?: number }
        const label = type === 'zscore' ? 'Z-Score' : type === 'mad' ? 'MAD' : type
        return (
            <div className="text-secondary pl-3">
                {label} {threshold != null ? threshold : ''}
            </div>
        )
    }

    const bounds = alert.threshold?.configuration?.bounds
    const isPercentage = alert.threshold?.configuration.type === InsightThresholdType.PERCENTAGE
    if (!bounds?.lower && !bounds?.upper) {
        return null
    }

    return (
        <div className="text-secondary pl-3">
            {bounds?.lower != null &&
                `Low ${isPercentage ? bounds.lower * 100 : bounds.lower}${isPercentage ? '%' : ''}`}
            {bounds?.lower != null && bounds?.upper != null ? ' · ' : ''}
            {bounds?.upper != null &&
                `High ${isPercentage ? bounds.upper * 100 : bounds.upper}${isPercentage ? '%' : ''}`}
        </div>
    )
}

export function AlertListItem({
    alert,
    destinationCount = 0,
    destinationsLoading = false,
    onClick,
    redesigned,
}: AlertListItemProps): JSX.Element {
    if (redesigned) {
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

    return (
        <LemonButton type="secondary" onClick={onClick} data-attr="alert-list-item" fullWidth>
            <div className="flex justify-between flex-auto items-center p-2">
                <div className="flex flex-row gap-3 items-center">
                    <span>{alert.name}</span>
                    <AlertStateIndicator alert={alert} />
                    <AlertSummary alert={alert} />
                </div>

                <ProfileBubbles limit={4} people={alert.subscribed_users?.map(({ email }) => ({ email }))} />
            </div>
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
    const redesigned = useFeatureFlag('ALERTS_REDESIGNED_EDIT_MODAL')

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
                    With alerts, PostHog will monitor your insight and notify you when certain conditions are met. We do
                    not evaluate alerts in real-time, but rather on a schedule (hourly, daily...).
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
                                redesigned={redesigned}
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
