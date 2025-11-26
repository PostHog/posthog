import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { useCallback } from 'react'

import { IconChevronLeft, IconInfo } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'

import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { alphabet, formatDate } from 'lib/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { SnoozeButton } from '../SnoozeButton'
import { alertFormLogic, canCheckOngoingInterval } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'
import { AlertType } from '../types'
import { AlertDestinationSelector } from './AlertDestinationSelector'

function alertCalculationIntervalToLabel(interval: AlertCalculationInterval): string {
    switch (interval) {
        case AlertCalculationInterval.HOURLY:
            return 'hour'
        case AlertCalculationInterval.DAILY:
            return 'day'
        case AlertCalculationInterval.WEEKLY:
            return 'week'
        case AlertCalculationInterval.MONTHLY:
            return 'month'
    }
}

export function AlertStateTable({ alert }: { alert: AlertType }): JSX.Element | null {
    if (!alert.checks || alert.checks.length === 0) {
        return null
    }

    return (
        <div className="bg-primary p-4 mt-10 rounded-lg">
            <div className="flex flex-row gap-2 items-center mb-2">
                <h3 className="m-0">Current status: </h3>
                <AlertStateIndicator alert={alert} />
                <h3 className="m-0">
                    {alert.snoozed_until && ` until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}
                </h3>
            </div>
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
                        <tr key={check.id} className={check.is_backfill ? 'opacity-70' : ''}>
                            <td className="flex items-center gap-1">
                                {check.state}
                                {check.is_backfill && (
                                    <LemonBadge size="small" status="muted">
                                        backfill
                                    </LemonBadge>
                                )}
                            </td>
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
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    insightLogicProps?: InsightLogicProps
}

export function EditAlertModal({
    isOpen,
    alertId,
    insightId,
    insightShortId,
    onClose,
    onEditSuccess,
    insightLogicProps,
}: EditAlertModalProps): JSX.Element {
    const _alertLogic = alertLogic({ alertId })
    const { alert, alertLoading } = useValues(_alertLogic)
    const { loadAlert } = useActions(_alertLogic)

    // Wait for alert to load before rendering the form (when editing)
    // This ensures the form logic is initialized with the correct alert data
    const isLoadingExistingAlert = alertId && alertLoading

    // need to reload edited alert as well
    const _onEditSuccess = useCallback(
        (alertId: AlertType['id'] | undefined) => {
            if (alertId) {
                loadAlert()
            }
            onEditSuccess(alertId)
        },
        [loadAlert, onEditSuccess]
    )

    if (isLoadingExistingAlert) {
        return (
            <LemonModal onClose={onClose} isOpen={isOpen} width={600} simple title="">
                <SpinnerOverlay />
            </LemonModal>
        )
    }

    return (
        <EditAlertModalForm
            alert={alert}
            insightId={insightId}
            insightShortId={insightShortId}
            insightLogicProps={insightLogicProps}
            onEditSuccess={_onEditSuccess}
            onClose={onClose}
            isOpen={isOpen}
        />
    )
}

interface EditAlertModalFormProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    insightLogicProps?: InsightLogicProps
    onEditSuccess: (alertId: AlertType['id'] | undefined) => void
    onClose?: () => void
    isOpen: boolean | undefined
}

function EditAlertModalForm({
    alert,
    insightId,
    insightShortId,
    insightLogicProps,
    onEditSuccess,
    onClose,
    isOpen,
}: EditAlertModalFormProps): JSX.Element {
    const formLogicProps = {
        alert,
        insightId,
        onEditSuccess,
        insightVizDataLogicProps: insightLogicProps,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const { alertForm, isAlertFormSubmitting, alertFormChanged, generateHistoricalForecasts } = useValues(formLogic)
    const { deleteAlert, snoozeAlert, clearSnooze, setGenerateHistoricalForecasts } = useActions(formLogic)
    const { setAlertFormValue } = useActions(formLogic)

    const trendsLogic = trendsDataLogic({ dashboardItemId: insightShortId })
    const {
        alertSeries,
        isNonTimeSeriesDisplay,
        isBreakdownValid,
        formulaNodes,
        interval: trendInterval,
    } = useValues(trendsLogic)

    const creatingNewAlert = alertForm.id === undefined
    // can only check ongoing interval for absolute value/increase alerts with upper threshold
    const can_check_ongoing_interval = canCheckOngoingInterval(alertForm)

    return (
        <LemonModal onClose={onClose} isOpen={isOpen} width={600} simple title="">
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
                    <div className="deprecated-space-y-8">
                        <div className="deprecated-space-y-4">
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
                                <UserActivityIndicator at={alert.created_at} by={alert.created_by} prefix="Created" />
                            ) : null}
                        </div>

                        <div className="deprecated-space-y-6">
                            <h3>Definition</h3>
                            <div className="deprecated-space-y-5">
                                {isBreakdownValid && (
                                    <LemonBanner type="warning">
                                        For trends with breakdown, the alert will fire if any of the breakdown values
                                        breaches the threshold.
                                    </LemonBanner>
                                )}
                                <div className="flex gap-4 items-center">
                                    <div>When</div>
                                    <Group name={['config']}>
                                        <LemonField name="series_index" className="flex-auto">
                                            <LemonSelect
                                                fullWidth
                                                data-attr="alertForm-series-index"
                                                options={
                                                    formulaNodes?.length > 0
                                                        ? formulaNodes.map(({ formula, custom_name }, index) => ({
                                                              label: `${
                                                                  custom_name ? custom_name : 'Formula'
                                                              } (${formula})`,
                                                              value: index,
                                                          }))
                                                        : (alertSeries?.map(({ custom_name, name, event }, index) => ({
                                                              label: isBreakdownValid
                                                                  ? 'any breakdown value'
                                                                  : `${alphabet[index]} - ${
                                                                        custom_name ?? name ?? event
                                                                    }`,
                                                              value: isBreakdownValid ? 0 : index,
                                                          })) ?? [])
                                                }
                                                disabledReason={
                                                    isBreakdownValid &&
                                                    `For trends with breakdown, the alert will fire if any of the breakdown
                                            values breaches the threshold.`
                                                }
                                            />
                                        </LemonField>
                                    </Group>
                                    <Group name={['condition']}>
                                        <LemonField name="type">
                                            <LemonSelect
                                                fullWidth
                                                className="w-48"
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
                                                    {
                                                        label: 'deviates from forecast',
                                                        value: AlertConditionType.FORECAST_DEVIATION,
                                                        disabledReason:
                                                            isNonTimeSeriesDisplay &&
                                                            'Forecast alerts require time series trends',
                                                    },
                                                ]}
                                            />
                                        </LemonField>
                                    </Group>
                                </div>
                                {alertForm.condition.type === AlertConditionType.FORECAST_DEVIATION ? (
                                    <div className="flex gap-4 items-center">
                                        <div>outside</div>
                                        <Group name={['config']}>
                                            <LemonField name="confidence_level">
                                                <LemonSelect
                                                    className="w-24"
                                                    data-attr="alertForm-confidence-level"
                                                    options={[
                                                        { label: '90%', value: 0.9 },
                                                        { label: '95%', value: 0.95 },
                                                        { label: '99%', value: 0.99 },
                                                    ]}
                                                />
                                            </LemonField>
                                        </Group>
                                        <div>confidence interval</div>
                                        <Tooltip
                                            title="Alert fires when the actual value falls outside the forecast confidence interval generated by the Chronos model"
                                            placement="right"
                                            delayMs={0}
                                        >
                                            <IconInfo />
                                        </Tooltip>
                                    </div>
                                ) : (
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
                                                                tooltip: 'Percent',
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
                                )}
                                <div className="flex gap-4 items-center">
                                    <div>Run alert every</div>
                                    <LemonField name="calculation_interval">
                                        <LemonSelect
                                            fullWidth
                                            className="w-28"
                                            data-attr="alertForm-calculation-interval"
                                            options={Object.values(AlertCalculationInterval).map((interval) => ({
                                                label: alertCalculationIntervalToLabel(interval),
                                                value: interval,
                                            }))}
                                        />
                                    </LemonField>
                                    <div>
                                        and check{' '}
                                        {'check_ongoing_interval' in alertForm?.config &&
                                        alertForm.config.check_ongoing_interval
                                            ? 'current'
                                            : 'last'}
                                    </div>
                                    <LemonSelect
                                        fullWidth
                                        className="w-28"
                                        data-attr="alertForm-trend-interval"
                                        disabledReason={
                                            <>
                                                To change the interval being checked, edit and <b>save</b> the interval
                                                which the insight is 'grouped by'
                                            </>
                                        }
                                        value={trendInterval ?? 'day'}
                                        options={[
                                            {
                                                label: trendInterval ?? 'day',
                                                value: trendInterval ?? 'day',
                                            },
                                        ]}
                                    />
                                </div>
                            </div>
                        </div>

                        <div>
                            <h3>Notification</h3>
                            <div className="flex gap-4 items-center mt-2">
                                <div>E-mail</div>
                                <div className="flex-auto">
                                    <MemberSelectMultiple
                                        value={alertForm.subscribed_users?.map((u) => u.id) ?? []}
                                        idKey="id"
                                        onChange={(value) => setAlertFormValue('subscribed_users', value)}
                                    />
                                </div>
                            </div>

                            <h4 className="mt-4">CDP Destinations</h4>
                            <div className="mt-2">
                                {alert?.id ? (
                                    <div className="flex flex-col">
                                        <AlertDestinationSelector alertId={alert.id} />
                                    </div>
                                ) : (
                                    <div className="text-muted-alt">
                                        Save alert first to add destinations (e.g. Slack, Webhooks)
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="deprecated-space-y-2">
                            <LemonCollapse
                                panels={[
                                    {
                                        key: 'advanced',
                                        header: 'Advanced options',
                                        content: (
                                            <div className="space-y-2">
                                                <Group name={['config']}>
                                                    <div className="flex gap-1">
                                                        <LemonField name="check_ongoing_interval">
                                                            <LemonCheckbox
                                                                checked={
                                                                    can_check_ongoing_interval &&
                                                                    'check_ongoing_interval' in alertForm?.config &&
                                                                    alertForm.config.check_ongoing_interval
                                                                }
                                                                data-attr="alertForm-check-ongoing-interval"
                                                                fullWidth
                                                                label="Check ongoing period"
                                                                disabledReason={
                                                                    !can_check_ongoing_interval &&
                                                                    'Can only alert for ongoing period when checking for absolute value/increase above a set upper threshold.'
                                                                }
                                                            />
                                                        </LemonField>
                                                        <Tooltip
                                                            title="Checks the insight value for the ongoing period (current week/month) that hasn't yet completed. Use this if you want to be alerted right away when the insight value rises/increases above threshold"
                                                            placement="right"
                                                            delayMs={0}
                                                        >
                                                            <IconInfo />
                                                        </Tooltip>
                                                    </div>
                                                </Group>
                                                <LemonField name="skip_weekend">
                                                    <LemonCheckbox
                                                        checked={
                                                            (alertForm?.calculation_interval ===
                                                                AlertCalculationInterval.DAILY ||
                                                                alertForm?.calculation_interval ===
                                                                    AlertCalculationInterval.HOURLY) &&
                                                            alertForm?.skip_weekend
                                                        }
                                                        data-attr="alertForm-skip-weekend"
                                                        fullWidth
                                                        label="Skip checking on weekends"
                                                        disabledReason={
                                                            alertForm?.calculation_interval !==
                                                                AlertCalculationInterval.DAILY &&
                                                            alertForm?.calculation_interval !==
                                                                AlertCalculationInterval.HOURLY &&
                                                            'Can only skip weekend checking for hourly/daily alerts'
                                                        }
                                                    />
                                                </LemonField>
                                                {alertForm.condition.type === AlertConditionType.FORECAST_DEVIATION && (
                                                    <div className="flex gap-1">
                                                        <LemonCheckbox
                                                            checked={generateHistoricalForecasts}
                                                            onChange={setGenerateHistoricalForecasts}
                                                            data-attr="alertForm-generate-historical-forecasts"
                                                            fullWidth
                                                            label="Generate historical forecasts"
                                                        />
                                                        <Tooltip
                                                            title="Generate forecasts for historical data points to visualize how the model would have performed. This runs in the background after the alert is saved."
                                                            placement="right"
                                                            delayMs={0}
                                                        >
                                                            <IconInfo />
                                                        </Tooltip>
                                                    </div>
                                                )}
                                            </div>
                                        ),
                                    },
                                ]}
                            />
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
        </LemonModal>
    )
}
