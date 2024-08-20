import { LemonCheckbox, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlerts'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { AlertType } from '~/queries/schema'

import { alertLogic, AlertLogicProps } from '../alertLogic'
import { alertsLogic } from '../alertsLogic'

interface EditAlertProps extends AlertLogicProps {
    onCancel: () => void
    onDelete: () => void
}

export function AlertState({ alert }: { alert: AlertType }): JSX.Element | null {
    if (!alert.checks || alert.checks.length === 0) {
        return null
    }

    return (
        <div className="bg-bg-3000 p-4 mt-10 rounded-lg">
            <h3>
                Current status {alert.state === 'firing' ? 'firing' : 'not met'}
                <AlertStateIndicator alert={alert} />
            </h3>
            <table className="w-full table-auto border-spacing-2 border-collapse">
                <thead>
                    <tr className="text-left">
                        <th>Status</th>
                        <th className="text-right">Time</th>
                        <th className="text-right pr-4">Value</th>
                        <th>Targets notified</th>
                    </tr>
                </thead>
                <tbody>
                    {alert.checks.map((check) => (
                        <tr key={check.id}>
                            <td>{check.state === 'firing' ? 'Firing' : 'Not met'}</td>
                            <td className="text-right">
                                <TZLabel time={check.created_at} />
                            </td>
                            <td className="text-right pr-4">{check.calculated_value}</td>
                            <td>{check.targets_notified ? 'Yes' : 'No'}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export function EditAlert(props: EditAlertProps): JSX.Element {
    const logic = alertLogic(props)
    const alertslogic = alertsLogic(props)

    const { alert, isAlertSubmitting, alertChanged } = useValues(logic)
    const { deleteAlert } = useActions(alertslogic)
    const id = props.id

    const _onDelete = (): void => {
        if (id) {
            deleteAlert(id)
            props.onDelete()
        }
    }

    return (
        <Form logic={alertLogic} props={props} formKey="alert" enableFormOnSubmit className="LemonModal__layout">
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={props.onCancel} size="xsmall" />

                    <h3>{!id ? 'New' : 'Edit '} Alert</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content>
                {!alert ? (
                    <div className="p-4 text-center">
                        <h2>Not found</h2>
                        <p>This alert could not be found. It may have been deleted.</p>
                    </div>
                ) : (
                    <>
                        <div className="space-y-2">
                            {alert?.created_by ? (
                                <UserActivityIndicator
                                    at={alert.created_at}
                                    by={alert.created_by}
                                    prefix="Created"
                                    className="mb-4"
                                />
                            ) : null}

                            <LemonField name="name" label="Name">
                                <LemonInput placeholder="e.g. High error rate" data-attr="alert-name" />
                            </LemonField>

                            <LemonField name="enabled">
                                <LemonCheckbox
                                    checked={alert.enabled}
                                    data-attr="alert-enabled"
                                    fullWidth
                                    label="Enabled"
                                />
                            </LemonField>

                            <Group name={['notification_targets']}>
                                <LemonField
                                    name="email"
                                    label="Who do you want to notify"
                                    help="Enter email addresses of the users you want notify"
                                >
                                    <LemonInputSelect
                                        mode="multiple"
                                        placeholder="Enter email addresses"
                                        allowCustomValues
                                        data-attr="alert-notification-targets"
                                    />
                                </LemonField>
                            </Group>

                            <Group name={['threshold', 'configuration', 'absoluteThreshold']}>
                                <span className="flex gap-10">
                                    <LemonField
                                        name="lower"
                                        label="Lower threshold"
                                        help="Notify if the value is strictly below"
                                    >
                                        <LemonInput type="number" className="w-20" data-attr="alert-lower-threshold" />
                                    </LemonField>
                                    <LemonField
                                        name="upper"
                                        label="Upper threshold"
                                        help="Notify if the value is strictly above"
                                    >
                                        <LemonInput type="number" className="w-20" data-attr="alert-upper-threshold" />
                                    </LemonField>
                                </span>
                            </Group>
                        </div>
                        <AlertState alert={alert} />
                    </>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {alert && id && (
                        <LemonButton type="secondary" status="danger" onClick={_onDelete}>
                            Delete alert
                        </LemonButton>
                    )}
                </div>
                <LemonButton type="secondary" onClick={props.onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" htmlType="submit" loading={isAlertSubmitting} disabled={!alertChanged}>
                    {!id ? 'Create alert' : 'Save'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
