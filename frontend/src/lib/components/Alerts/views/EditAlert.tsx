import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { alertLogic, AlertLogicProps } from '../alertLogic'
import { alertsLogic } from '../alertsLogic'

interface EditAlertProps extends AlertLogicProps {
    onCancel: () => void
    onDelete: () => void
}

export function EditAlert(props: EditAlertProps): JSX.Element {
    const logic = alertLogic(props)
    const alertslogic = alertsLogic(props)

    const { alert, isAlertSubmitting, alertChanged } = useValues(logic)
    const { deleteAlert } = useActions(alertslogic)
    const id = props.id

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteAlert(id)
            props.onDelete()
        }
    }

    return (
        <Form logic={alertLogic} props={props} formKey="alert" enableFormOnSubmit className="LemonModal__layout">
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={props.onCancel} size="xsmall" />

                    <h3>{id === 'new' ? 'New' : 'Edit '} Alert</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content className="space-y-2">
                {!alert ? (
                    <div className="p-4 text-center">
                        <h2>Not found</h2>
                        <p>This alert could not be found. It may have been deleted.</p>
                    </div>
                ) : (
                    <>
                        <LemonField name="name" label="Name">
                            <LemonInput placeholder="e.g. High error rate" data-attr="alert-name" />
                        </LemonField>

                        <LemonField
                            name="target_value"
                            label="Who do you want to notify about anomalies"
                            help="Enter comma separated email addresses of the users you want notify about anomalies"
                        >
                            <LemonInput data-attr="alert-notification-targets" placeholder="Enter an email address" />
                        </LemonField>
                        <Group name={['anomaly_condition', 'absoluteThreshold']}>
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
                    </>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {alert && id !== 'new' && (
                        <LemonButton type="secondary" status="danger" onClick={_onDelete}>
                            Delete alert
                        </LemonButton>
                    )}
                </div>
                <LemonButton type="secondary" onClick={props.onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" htmlType="submit" loading={isAlertSubmitting} disabled={!alertChanged}>
                    {id === 'new' ? 'Create alert' : 'Save'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
