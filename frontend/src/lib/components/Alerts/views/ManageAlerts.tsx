import { IconEllipsis } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { pluralize } from 'lib/utils'

import { AlertType } from '~/types'

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
                    <div className="text-link font-medium">{alert.name}</div>
                </div>
                <ProfileBubbles limit={4} people={alert.target_value.split(',').map((email) => ({ email }))} />
            </div>
        </LemonButton>
    )
}

interface ManageAlertsProps extends AlertsLogicProps {
    onCancel: () => void
    onSelect: (value: number | 'new') => void
}

export function ManageAlerts(props: ManageAlertsProps): JSX.Element {
    const logic = alertsLogic(props)

    const { alerts } = useValues(logic)
    const { deleteAlert } = useActions(logic)

    return (
        <>
            <LemonModal.Header>
                <h3> Manage Alerts</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                {alerts.length ? (
                    <div className="space-y-2">
                        <div>
                            <strong>{alerts?.length}</strong>
                            {' active '}
                            {pluralize(alerts.length || 0, 'alert', 'alerts', false)}
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
                <LemonButton type="secondary" onClick={props.onCancel}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </>
    )
}
