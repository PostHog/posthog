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

import { AlertCalculationInterval, AlertType } from '~/queries/schema'
import { QueryBasedInsightModel } from '~/types'

import { alertFormLogic, AlertFormType } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'

interface EditAlertProps {
    isOpen: boolean | undefined
    alertId?: string
    insight?: Partial<QueryBasedInsightModel>
    onEditSuccess: () => void
    onClose?: () => void
}

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

export function EditAlertModal({ alertId, onClose, isOpen, onEditSuccess, insight }: EditAlertProps): JSX.Element {
    if (!alertId && !insight) {
        throw new Error('Must provide either an alertId or an insight to create alert for')
    }

    const { alert, alertLoading } = useValues(alertLogic({ alertId }))

    if (alertLoading) {
        return <SpinnerOverlay />
    }

    return (
        <LemonModal onClose={onClose} isOpen={isOpen} width={600} simple title="">
            {alert ? (
                <EditAlertForm
                    alert={alert}
                    onClose={onClose}
                    onEditSuccess={onEditSuccess}
                    alertState={<AlertStateTable alert={alert} />}
                />
            ) : alertId !== undefined ? (
                // we have alertId but didn't get alert
                <div className="p-4 text-center">
                    <h2>Not found</h2>
                    <p>This alert could not be found. It may have been deleted.</p>
                </div>
            ) : // we need to create a new alert
            insight === undefined ? (
                <div className="p-4 text-center">
                    <p>Can only create new alert in context of an insight</p>
                </div>
            ) : (
                <EditAlertForm
                    alert={
                        {
                            id: undefined,
                            name: '',
                            created_by: null,
                            created_at: '',
                            enabled: true,
                            config: {
                                type: 'TrendsAlertConfig',
                                series_index: 0,
                            },
                            threshold: {
                                configuration: {
                                    absoluteThreshold: {},
                                },
                            },
                            subscribed_users: [],
                            checks: [],
                            insight: insight.id,
                            insight_short_id: insight.short_id,
                        } as AlertFormType
                    }
                    onClose={onClose}
                    onEditSuccess={onEditSuccess}
                />
            )}
        </LemonModal>
    )
}

interface EditAlertFormProps {
    alert: AlertFormType
    onEditSuccess: () => void
    onClose?: () => void
    alertState?: JSX.Element
}

function EditAlertForm({ alert, onClose, onEditSuccess, alertState }: EditAlertFormProps): JSX.Element {
    const formLogicProps = { alert, onEditSuccess, onCreateSuccess: onClose, onDeleteSuccess: onClose }
    const formLogic = alertFormLogic(formLogicProps)
    const { alert: alertForm, isAlertSubmitting, alertChanged } = useValues(formLogic)
    const { deleteAlert } = useActions(formLogic)
    const { setAlertValue } = useActions(formLogic)

    const trendsLogic = trendsDataLogic({ dashboardItemId: alert.insight_short_id })
    const { alertSeries, breakdownFilter } = useValues(trendsLogic)

    const creatingNewAlert = alertForm.id === undefined

    return (
        <Form
            logic={alertFormLogic}
            props={formLogicProps}
            formKey="alert"
            enableFormOnSubmit
            className="LemonModal__layout"
        >
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={onClose} size="xsmall" />

                    <h3>{creatingNewAlert === undefined ? 'New' : 'Edit '} Alert</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="space-y-2">
                    {alert.created_by ? (
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
                            checked={alertForm?.enabled}
                            data-attr="alert-enabled"
                            fullWidth
                            label="Enabled"
                        />
                    </LemonField>

                    {breakdownFilter && (
                        <LemonBanner type="warning" className="mb-4">
                            <span>
                                Alerts on insights with breakdowns alert when any of the breakdown values breaches the
                                threshold
                            </span>
                        </LemonBanner>
                    )}

                    <Group name={['config']}>
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
                    </Group>

                    <LemonField name="calculation_interval" label="Calculation Interval">
                        <LemonSelect
                            fullWidth
                            data-attr="alert-calculation-interval"
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

                    <MemberSelectMultiple
                        value={alertForm.subscribed_users?.map((u) => u.id) ?? []}
                        idKey="id"
                        onChange={(value) => setAlertValue('subscribed_users', value)}
                    />
                </div>
                {alertState}
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
                    loading={isAlertSubmitting}
                    disabledReason={!alertChanged && 'No changes to save'}
                >
                    {creatingNewAlert ? 'Create alert' : 'Save'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
