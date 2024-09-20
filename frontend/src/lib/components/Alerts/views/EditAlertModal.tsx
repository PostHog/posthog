import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { alphabet } from 'lib/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { AlertType } from '~/queries/schema'

import { alertLogic, AlertLogicProps } from '../alertLogic'

interface EditAlertProps extends AlertLogicProps {
    isOpen: boolean | undefined
    onClose?: () => void
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

export function EditAlertModal({ alertId, onClose, isOpen, onEditSuccess }: EditAlertProps): JSX.Element {
    const alertLogicProps = { alertId, onEditSuccess }
    const logic = alertLogic(alertLogicProps)

    const { alert, isAlertSubmitting, alertChanged } = useValues(logic)
    const { deleteAlert } = useActions(logic)

    const trendsLogic = trendsDataLogic({ dashboardItemId: alert.insight_short_id })
    const { alertSeries, calculationIntervalsForAlerts } = useValues(trendsLogic)

    const { setAlertValue } = useActions(logic)

    return (
        <LemonModal onClose={onClose} isOpen={isOpen} width={600} simple title="">
            <Form
                logic={alertLogic}
                props={alertLogicProps}
                formKey="alert"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <LemonModal.Header>
                    <div className="flex items-center gap-2">
                        <LemonButton icon={<IconChevronLeft />} onClick={onClose} size="xsmall" />

                        <h3>{!alertId ? 'New' : 'Edit '} Alert</h3>
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

                                <LemonField name="series_index" label="Series">
                                    <LemonSelect
                                        fullWidth
                                        data-attr="alert-series-index"
                                        options={alertSeries.map(({ event }, index) => ({
                                            label: `${alphabet[index]} - ${event}`,
                                            value: index,
                                        }))}
                                    />
                                </LemonField>

                                <LemonField name="calculation_interval" label="Calculation Interval">
                                    <LemonSelect
                                        fullWidth
                                        data-attr="alert-calculation-interval"
                                        options={calculationIntervalsForAlerts.map((interval) => ({
                                            label: interval,
                                            value: interval,
                                        }))}
                                    />
                                </LemonField>

                                <Group name={['threshold', 'configuration', 'absoluteThreshold']}>
                                    <span className="flex gap-10">
                                        <LemonField
                                            name="lower"
                                            label="Lower threshold"
                                            help="Notify if the value is strictly below"
                                        >
                                            <LemonInput
                                                type="number"
                                                className="w-20"
                                                data-attr="alert-lower-threshold"
                                            />
                                        </LemonField>
                                        <LemonField
                                            name="upper"
                                            label="Upper threshold"
                                            help="Notify if the value is strictly above"
                                        >
                                            <LemonInput
                                                type="number"
                                                className="w-20"
                                                data-attr="alert-upper-threshold"
                                            />
                                        </LemonField>
                                    </span>
                                </Group>

                                <MemberSelectMultiple
                                    value={alert.subscribed_users?.map((u) => u.id) ?? []}
                                    idKey="id"
                                    onChange={(value) => setAlertValue('subscribed_users', value)}
                                />
                            </div>
                            <AlertState alert={alert} />
                        </>
                    )}
                </LemonModal.Content>

                <LemonModal.Footer>
                    <div className="flex-1">
                        {alert && (
                            <LemonButton type="secondary" status="danger" onClick={deleteAlert}>
                                Delete alert
                            </LemonButton>
                        )}
                    </div>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isAlertSubmitting}
                        disabledReason={!alertChanged && 'No changes to save'}
                    >
                        {!alertId ? 'Create alert' : 'Save'}
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
