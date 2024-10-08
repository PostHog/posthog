import { IconCheck, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { AlertState, InsightThresholdType } from '~/queries/schema'
import { InsightShortId } from '~/types'

import { insightAlertsLogic, InsightAlertsLogicProps } from '../insightAlertsLogic'
import { AlertType } from '../types'

export function AlertStateIndicator({ alert }: { alert: AlertType }): JSX.Element {
    return alert.state === AlertState.NOT_FIRING ? (
        <span className="text-success-dark">
            <IconCheck />
        </span>
    ) : (
        <span className="text-danger-dark">
            <IconX />
        </span>
    )
}

interface AlertListItemProps {
    alert: AlertType
    onClick: () => void
}

export function AlertListItem({ alert, onClick }: AlertListItemProps): JSX.Element {
    const bounds = alert.threshold?.configuration?.bounds
    const isPercentage = alert.threshold?.configuration.type === InsightThresholdType.PERCENTAGE

    return (
        <LemonButton type="secondary" onClick={onClick} data-attr="alert-list-item" fullWidth>
            <div className="flex justify-between flex-auto items-center p-2">
                <div className="flex flex-row gap-3 items-center">
                    <AlertStateIndicator alert={alert} />
                    <span>{alert.name}</span>

                    {alert.enabled ? (
                        <div className="text-muted pl-3">
                            {bounds?.lower &&
                                `Low ${isPercentage ? bounds.lower * 100 : bounds.lower}${isPercentage ? '%' : ''}`}
                            {bounds?.lower && bounds?.upper ? ' · ' : ''}
                            {bounds?.upper &&
                                `High ${isPercentage ? bounds.upper * 100 : bounds.upper}${isPercentage ? '%' : ''}`}
                        </div>
                    ) : (
                        <div className="text-muted pl-3">Disabled</div>
                    )}
                </div>

                <ProfileBubbles limit={4} people={alert.subscribed_users?.map(({ email }) => ({ email }))} />
            </div>
        </LemonButton>
    )
}

interface ManageAlertsModalProps extends InsightAlertsLogicProps {
    isOpen: boolean
    insightShortId: InsightShortId
    onClose?: () => void
}

export function ManageAlertsModal(props: ManageAlertsModalProps): JSX.Element {
    const { push } = useActions(router)
    const logic = insightAlertsLogic(props)

    const { alerts } = useValues(logic)

    return (
        <LemonModal onClose={props.onClose} isOpen={props.isOpen} width={600} simple title="">
            <LemonModal.Header>
                <h3>
                    Manage Alerts <LemonTag type="warning">ALPHA</LemonTag>
                </h3>
            </LemonModal.Header>
            <LemonModal.Content>
                <div className="mb-4">
                    With alerts, PostHog will monitor your insight and notify you when certain conditions are met. We do
                    not evaluate alerts in real-time, but rather on a schedule (hourly, daily...). Please note that
                    alerts are in alpha and may not be fully reliable.
                </div>
                {alerts.length ? (
                    <div className="space-y-2">
                        <div>
                            <strong>{alerts?.length}</strong> {pluralize(alerts.length || 0, 'alert', 'alerts', false)}
                        </div>

                        {alerts.map((alert) => (
                            <AlertListItem
                                key={alert.id}
                                alert={alert}
                                onClick={() => push(urls.insightAlert(props.insightShortId, alert.id))}
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
                <LemonButton type="primary" onClick={() => push(urls.insightAlert(props.insightShortId, 'new'))}>
                    New alert
                </LemonButton>
                <LemonButton type="secondary" onClick={props.onClose}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
