import { IconEllipsis } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { AlertType } from '~/queries/schema'

import { alertsLogic, AlertsLogicProps } from '../alertsLogic'

interface AlertListItemProps {
    alert: AlertType
    onClick: () => void
    onDelete?: () => void
}

export function AlertListItem({ alert, onClick, onDelete }: AlertListItemProps): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            onClick={onClick}
            data-attr="alert-list-item"
            fullWidth
            sideAction={{
                icon: <IconEllipsis />,
                dropdown: {
                    overlay: (
                        <>
                            {onDelete && (
                                <LemonButton
                                    onClick={onDelete}
                                    data-attr="alert-list-item-delete"
                                    status="danger"
                                    fullWidth
                                >
                                    Delete Alert
                                </LemonButton>
                            )}
                        </>
                    ),
                },
            }}
        >
            <div className="flex justify-between flex-auto items-center p-2">
                <div>
                    <div className="text-link font-medium">
                        {alert.name}
                        {alert.state === 'firing' ? (
                            <span className="inline-block align-middle rounded-full w-4 h-4 mx-2 bg-danger-light" />
                        ) : (
                            <span className="inline-block align-middle rounded-full w-4 h-4 mx-2 bg-success-light" />
                        )}
                        <span className="text-xs text-muted">
                            {alert.condition.absoluteThreshold?.lower
                                ? ` < ${alert.condition.absoluteThreshold.lower}`
                                : ''}{' '}
                            {alert.condition.absoluteThreshold?.upper
                                ? ` > ${alert.condition.absoluteThreshold.upper}`
                                : ''}
                        </span>
                    </div>
                </div>
                <ProfileBubbles limit={4} people={alert.notification_targets?.email?.map((email) => ({ email }))} />
            </div>
        </LemonButton>
    )
}

interface ManageAlertsProps extends AlertsLogicProps {
    onCancel: () => void
    onSelect: (value?: string) => void
}

export function ManageAlerts(props: ManageAlertsProps): JSX.Element {
    const { push } = useActions(router)
    const logic = alertsLogic(props)

    const { alerts } = useValues(logic)
    const { deleteAlert } = useActions(logic)

    return (
        <>
            <LemonModal.Header>
                <h3>Manage Alerts</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                {alerts.length ? (
                    <div className="space-y-2">
                        <div>
                            <strong>{alerts?.length}</strong> {pluralize(alerts.length || 0, 'alert', 'alerts', false)}
                        </div>

                        {alerts.map((alert) => (
                            <AlertListItem
                                key={alert.id}
                                alert={alert}
                                onClick={() => props.onSelect(alert.id)}
                                onDelete={() => deleteAlert(alert.id)}
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
                <LemonButton type="primary" onClick={() => push(urls.alert(props.insightShortId, 'new'))}>
                    New alert
                </LemonButton>
                <LemonButton type="secondary" onClick={props.onCancel}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </>
    )
}
