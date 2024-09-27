import { LemonBanner, LemonCheckbox, LemonInput, LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'
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

import { AlertCalculationInterval } from '~/queries/schema'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

import { alertFormLogic } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'
import { AlertType } from '../types'

export function AlertStateTable({ alert }: { alert: AlertType }): JSX.Element | null {
    if (!alert.checks || alert.checks.length === 0) {
        return null
    }

    return (
        <div className="bg-bg-3000 p-4 mt-10 rounded-lg">
            <h3>
                Current status {alert.state}
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
                            <td>{check.state}</td>
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

interface EditAlertModalProps {
    isOpen: boolean | undefined
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    onEditSuccess: () => void
    onClose?: () => void
}

export function EditAlertModal({
    isOpen,
    alertId,
    insightId,
    insightShortId,
    onClose,
    onEditSuccess,
}: EditAlertModalProps): JSX.Element {
    const { alert, alertLoading } = useValues(alertLogic({ alertId }))

    const formLogicProps = { alert, insightId, onEditSuccess, onCreateSuccess: onClose, onDeleteSuccess: onClose }
    const formLogic = alertFormLogic(formLogicProps)
    const { alertForm, isAlertFormSubmitting, alertFormChanged } = useValues(formLogic)
    const { deleteAlert } = useActions(formLogic)
    const { setAlertFormValue } = useActions(formLogic)

    const trendsLogic = trendsDataLogic({ dashboardItemId: insightShortId })
    const { alertSeries, breakdownFilter } = useValues(trendsLogic)

    const creatingNewAlert = alertForm.id === undefined

    return (
        <LemonModal onClose={onClose} isOpen={isOpen} width={600} simple title="">
            {alertLoading ? (
                <SpinnerOverlay />
            ) : (
                <Form
                    logic={alertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    <LemonModal.Header>
                        <div className="flex items-center gap-2">
                            <LemonButton icon={<IconChevronLeft />} onClick={onClose} size="xsmall" />

                            <h3>{creatingNewAlert ? 'New' : 'Edit '} Alert</h3>
                        </div>
                    </LemonModal.Header>

                    <LemonModal.Content>
                        <div className="space-y-4">
                            {alert?.created_by ? (
                                <UserActivityIndicator
                                    at={alert.created_at}
                                    by={alert.created_by}
                                    prefix="Created"
                                    className="mb-4"
                                />
                            ) : null}

                            <LemonField name="name" label="Name">
                                <LemonInput placeholder="e.g. High error rate" data-attr="alertForm-name" />
                            </LemonField>

                            <LemonField name="enabled">
                                <LemonCheckbox
                                    checked={alertForm?.enabled}
                                    data-attr="alertForm-enabled"
                                    fullWidth
                                    label="Enabled"
                                />
                            </LemonField>

                            {breakdownFilter && (
                                <LemonBanner type="warning" className="mb-4">
                                    <span>
                                        Alerts on insights with breakdowns alert when any of the breakdown values
                                        breaches the threshold
                                    </span>
                                </LemonBanner>
                            )}

                            <Group name={['config']}>
                                <LemonField name="series_index" label="Series">
                                    <LemonSelect
                                        fullWidth
                                        data-attr="alertForm-series-index"
                                        options={alertSeries.map(({ event }, index) => ({
                                            label: `${alphabet[index]} - ${event}`,
                                            value: index,
                                        }))}
                                    />
                                </LemonField>
                            </Group>

                            <LemonField name="calculation_interval" label="Calculation Interval">
                                <LemonSelect
                                    fullWidth
                                    data-attr="alertForm-calculation-interval"
                                    options={Object.values(AlertCalculationInterval)
                                        // TODO: support all intervals by setting up celery jobs
                                        .filter((interval) => ['hourly', 'daily'].includes(interval))
                                        .map((interval) => ({
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
                                            data-attr="alertForm-lower-threshold"
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
                                            data-attr="alertForm-upper-threshold"
                                        />
                                    </LemonField>
                                </span>
                            </Group>

                            <MemberSelectMultiple
                                value={alertForm.subscribed_users?.map((u) => u.id) ?? []}
                                idKey="id"
                                onChange={(value) => setAlertFormValue('subscribed_users', value)}
                            />
                        </div>
                        {alert && <AlertStateTable alert={alert} />}
                    </LemonModal.Content>

                    <LemonModal.Footer>
                        <div className="flex-1">
                            {!creatingNewAlert ? (
                                <LemonButton type="secondary" status="danger" onClick={deleteAlert}>
                                    Delete alert
                                </LemonButton>
                            ) : null}
                        </div>
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isAlertFormSubmitting}
                            disabledReason={!alertFormChanged && 'No changes to save'}
                        >
                            {creatingNewAlert ? 'Create alert' : 'Save'}
                        </LemonButton>
                    </LemonModal.Footer>
                </Form>
            )}
        </LemonModal>
    )
}
