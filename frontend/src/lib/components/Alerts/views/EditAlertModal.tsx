import { LemonCheckbox, LemonInput, LemonSegmentedButton, LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { alphabet, formatDate } from 'lib/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { AlertCalculationInterval, AlertConditionType, AlertState, InsightThresholdType } from '~/queries/schema'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

import { alertFormLogic } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'
import { SnoozeButton } from '../SnoozeButton'
import { AlertType } from '../types'

export function AlertStateTable({ alert }: { alert: AlertType }): JSX.Element | null {
    if (!alert.checks || alert.checks.length === 0) {
        return null
    }

    return (
        <div className="bg-bg-3000 p-4 mt-10 rounded-lg">
            <h3>
                Current status - {alert.state}
                {alert.snoozed_until && ` until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}{' '}
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

    const formLogicProps = { alert, insightId, onEditSuccess }
    const formLogic = alertFormLogic(formLogicProps)
    const { alertForm, isAlertFormSubmitting, alertFormChanged } = useValues(formLogic)
    const { deleteAlert, snoozeAlert, clearSnooze } = useActions(formLogic)
    const { setAlertFormValue } = useActions(formLogic)

    const trendsLogic = trendsDataLogic({ dashboardItemId: insightShortId })
    const { alertSeries, isNonTimeSeriesDisplay } = useValues(trendsLogic)

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
                        <div className="space-y-8">
                            <div className="space-y-4">
                                <div className="flex gap-4 items-center">
                                    <LemonField className="flex-auto" name="name">
                                        <LemonInput placeholder="Alert name" data-attr="alertForm-name" />
                                    </LemonField>
                                    <LemonField name="enabled">
                                        <LemonCheckbox
                                            checked={alertForm?.enabled}
                                            data-attr="alertForm-enabled"
                                            fullWidth
                                            label="Enabled"
                                        />
                                    </LemonField>
                                </div>
                                {alert?.created_by ? (
                                    <UserActivityIndicator
                                        at={alert.created_at}
                                        by={alert.created_by}
                                        prefix="Created"
                                        // className="mb-4"
                                    />
                                ) : null}
                            </div>

                            <div className="space-y-6">
                                <h3>Definition</h3>
                                <div className="space-y-5">
                                    <div className="flex gap-4 items-center">
                                        <div>When</div>
                                        <Group name={['config']}>
                                            <LemonField name="series_index" className="flex-auto">
                                                <LemonSelect
                                                    fullWidth
                                                    data-attr="alertForm-series-index"
                                                    options={alertSeries?.map(({ event }, index) => ({
                                                        label: `${alphabet[index]} - ${event}`,
                                                        value: index,
                                                    }))}
                                                />
                                            </LemonField>
                                        </Group>
                                        <Group name={['condition']}>
                                            <LemonField name="type">
                                                <LemonSelect
                                                    fullWidth
                                                    className="w-40"
                                                    data-attr="alertForm-condition"
                                                    options={[
                                                        {
                                                            label: 'has value',
                                                            value: AlertConditionType.ABSOLUTE_VALUE,
                                                        },
                                                        {
                                                            label: 'increases by',
                                                            value: AlertConditionType.RELATIVE_INCREASE,
                                                            disabledReason:
                                                                isNonTimeSeriesDisplay &&
                                                                'This condition is only supported for time series trends',
                                                        },
                                                        {
                                                            label: 'decreases by',
                                                            value: AlertConditionType.RELATIVE_DECREASE,
                                                            disabledReason:
                                                                isNonTimeSeriesDisplay &&
                                                                'This condition is only supported for time series trends',
                                                        },
                                                    ]}
                                                />
                                            </LemonField>
                                        </Group>
                                    </div>
                                    <div className="flex gap-4 items-center">
                                        <div>less than</div>
                                        <LemonField name="lower">
                                            <LemonInput
                                                type="number"
                                                className="w-30"
                                                data-attr="alertForm-lower-threshold"
                                                value={
                                                    alertForm.threshold.configuration.type ===
                                                        InsightThresholdType.PERCENTAGE &&
                                                    alertForm.threshold.configuration.bounds?.lower
                                                        ? alertForm.threshold.configuration.bounds?.lower * 100
                                                        : alertForm.threshold.configuration.bounds?.lower
                                                }
                                                onChange={(value) =>
                                                    setAlertFormValue('threshold', {
                                                        configuration: {
                                                            type: alertForm.threshold.configuration.type,
                                                            bounds: {
                                                                ...alertForm.threshold.configuration.bounds,
                                                                lower:
                                                                    value &&
                                                                    alertForm.threshold.configuration.type ===
                                                                        InsightThresholdType.PERCENTAGE
                                                                        ? value / 100
                                                                        : value,
                                                            },
                                                        },
                                                    })
                                                }
                                            />
                                        </LemonField>
                                        <div>or more than</div>
                                        <LemonField name="upper">
                                            <LemonInput
                                                type="number"
                                                className="w-30"
                                                data-attr="alertForm-upper-threshold"
                                                value={
                                                    alertForm.threshold.configuration.type ===
                                                        InsightThresholdType.PERCENTAGE &&
                                                    alertForm.threshold.configuration.bounds?.upper
                                                        ? alertForm.threshold.configuration.bounds?.upper * 100
                                                        : alertForm.threshold.configuration.bounds?.upper
                                                }
                                                onChange={(value) =>
                                                    setAlertFormValue('threshold', {
                                                        configuration: {
                                                            type: alertForm.threshold.configuration.type,
                                                            bounds: {
                                                                ...alertForm.threshold.configuration.bounds,
                                                                upper:
                                                                    value &&
                                                                    alertForm.threshold.configuration.type ===
                                                                        InsightThresholdType.PERCENTAGE
                                                                        ? value / 100
                                                                        : value,
                                                            },
                                                        },
                                                    })
                                                }
                                            />
                                        </LemonField>
                                        {alertForm.condition.type !== AlertConditionType.ABSOLUTE_VALUE && (
                                            <Group name={['threshold', 'configuration']}>
                                                <LemonField name="type">
                                                    <LemonSegmentedButton
                                                        options={[
                                                            {
                                                                value: InsightThresholdType.PERCENTAGE,
                                                                label: '%',
                                                                tooltip: 'Percentage',
                                                            },
                                                            {
                                                                value: InsightThresholdType.ABSOLUTE,
                                                                label: '#',
                                                                tooltip: 'Absolute number',
                                                            },
                                                        ]}
                                                    />
                                                </LemonField>
                                            </Group>
                                        )}
                                    </div>
                                    <div className="flex gap-4 items-center">
                                        <div>
                                            {alertForm.condition.type === AlertConditionType.ABSOLUTE_VALUE
                                                ? 'check'
                                                : 'compare'}
                                        </div>
                                        <LemonField name="calculation_interval">
                                            <LemonSelect
                                                fullWidth
                                                className="w-28"
                                                data-attr="alertForm-calculation-interval"
                                                options={Object.values(AlertCalculationInterval).map((interval) => ({
                                                    label: interval,
                                                    value: interval,
                                                }))}
                                            />
                                        </LemonField>
                                        <div>and notify</div>
                                        <div className="flex-auto">
                                            <MemberSelectMultiple
                                                value={alertForm.subscribed_users?.map((u) => u.id) ?? []}
                                                idKey="id"
                                                onChange={(value) => setAlertFormValue('subscribed_users', value)}
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        {alert && <AlertStateTable alert={alert} />}
                    </LemonModal.Content>

                    <LemonModal.Footer>
                        <div className="flex-1">
                            <div className="flex gap-2">
                                {!creatingNewAlert ? (
                                    <LemonButton type="secondary" status="danger" onClick={deleteAlert}>
                                        Delete alert
                                    </LemonButton>
                                ) : null}
                                {!creatingNewAlert && alert?.state === AlertState.FIRING ? (
                                    <SnoozeButton onChange={snoozeAlert} value={alert?.snoozed_until} />
                                ) : null}
                                {!creatingNewAlert && alert?.state === AlertState.SNOOZED ? (
                                    <LemonButton
                                        type="secondary"
                                        status="default"
                                        onClick={clearSnooze}
                                        tooltip={`Currently snoozed until ${formatDate(
                                            dayjs(alert?.snoozed_until),
                                            'MMM D, HH:mm'
                                        )}`}
                                    >
                                        Clear snooze
                                    </LemonButton>
                                ) : null}
                            </div>
                        </div>
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
