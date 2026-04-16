import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { useCallback, useMemo } from 'react'

import { IconCalendar, IconChevronLeft, IconClock, IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    Link,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { alphabet, formatDate } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { alertFormLogic, canCheckOngoingInterval, getDefaultSimulationRange } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'
import { alertNotificationLogic } from '../alertNotificationLogic'
import { isNextPlannedEvaluationStale } from '../alertSchedulingStale'
import { insightAlertsLogic } from '../insightAlertsLogic'
import { SnoozeButton } from '../SnoozeButton'
import type { AlertType } from '../types'
import { AlertDestinationSelector } from './AlertDestinationSelector'
import { AlertStateTable } from './AlertStateTable'
import { DetectorSelector, getDefaultWindow } from './DetectorSelector'
import { InlineAlertNotifications } from './InlineAlertNotifications'
import { QuietHoursFields } from './QuietHoursFields'
import { SimulationSummary } from './SimulationSummary'

function getSimulationRangeOptions(interval: AlertCalculationInterval): { label: string; value: string }[] {
    switch (interval) {
        case AlertCalculationInterval.HOURLY:
            return [
                { label: 'Last 24h', value: '-24h' },
                { label: 'Last 48h', value: '-48h' },
                { label: 'Last 72h', value: '-72h' },
                { label: 'Last 7d', value: '-168h' },
            ]
        case AlertCalculationInterval.DAILY:
            return [
                { label: 'Last 14d', value: '-14d' },
                { label: 'Last 30d', value: '-30d' },
                { label: 'Last 60d', value: '-60d' },
                { label: 'Last 90d', value: '-90d' },
            ]
        case AlertCalculationInterval.WEEKLY:
            return [
                { label: 'Last 8w', value: '-8w' },
                { label: 'Last 12w', value: '-12w' },
                { label: 'Last 26w', value: '-26w' },
                { label: 'Last 52w', value: '-52w' },
            ]
        case AlertCalculationInterval.MONTHLY:
            return [
                { label: 'Last 6m', value: '-6m' },
                { label: 'Last 12m', value: '-12m' },
                { label: 'Last 24m', value: '-24m' },
            ]
    }
}

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

    /** Parent callback only (e.g. close modal). `alertLogic` is hydrated from the save response inside `alertFormLogic`. */
    const _onEditSuccess = useCallback(
        (alertId: AlertType['id'] | undefined) => {
            onEditSuccess(alertId)
        },
        [onEditSuccess]
    )

    const trendsLogic = trendsDataLogic({ dashboardItemId: insightShortId })
    const {
        alertSeries,
        isNonTimeSeriesDisplay,
        isBreakdownValid,
        formulaNodes,
        interval: trendInterval,
    } = useValues(trendsLogic)

    const formLogicProps = {
        alert,
        insightId,
        onEditSuccess: _onEditSuccess,
        insightVizDataLogicProps: insightLogicProps,
        insightInterval: trendInterval ?? undefined,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const {
        alertForm,
        isAlertFormSubmitting,
        alertFormChanged,
        simulationResult,
        simulationResultLoading,
        simulationDateFrom,
    } = useValues(formLogic)
    const { deleteAlert, snoozeAlert, clearSnooze, simulateAlert, clearSimulation, setSimulationDateFrom } =
        useActions(formLogic)
    const { setAlertFormValue } = useActions(formLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const projectTimezone = currentTeam?.timezone ?? 'UTC'
    const anomalyDetectionEnabled = !!featureFlags[FEATURE_FLAGS.ALERTS_ANOMALY_DETECTION]
    const inlineNotificationsEnabled = !!featureFlags[FEATURE_FLAGS.ALERTS_INLINE_NOTIFICATIONS]
    const quietHoursEnabled = !!featureFlags[FEATURE_FLAGS.ALERTS_QUIET_HOURS]

    const { pendingNotifications } = useValues(alertNotificationLogic({ alertId: alertId }))
    const hasPendingNotifications = inlineNotificationsEnabled && pendingNotifications.length > 0

    const handleClose = useCallback(() => {
        clearSimulation()
        if (insightLogicProps && insightId) {
            insightAlertsLogic({ insightId, insightLogicProps }).actions.clearSimulationAnomalyPoints()
        }
        onClose?.()
    }, [clearSimulation, insightLogicProps, insightId, onClose])

    const clearSimulationOverlay = useCallback(() => {
        if (insightLogicProps && insightId) {
            insightAlertsLogic({ insightId, insightLogicProps }).actions.clearSimulationAnomalyPoints()
        }
    }, [insightLogicProps, insightId])

    const creatingNewAlert = alertForm.id === undefined
    // can only check ongoing interval for absolute value/increase alerts with upper threshold
    const can_check_ongoing_interval = canCheckOngoingInterval(alertForm)
    const alertMode = alertForm.detector_config ? 'detector' : 'threshold'
    const nextPlannedEvaluationStale = useMemo(
        () =>
            isNextPlannedEvaluationStale(creatingNewAlert, alert, {
                calculation_interval: alertForm.calculation_interval,
                schedule_restriction: alertForm.schedule_restriction,
                skip_weekend: alertForm.skip_weekend,
                config: alertForm.config,
            }),
        [
            alert,
            alertForm.calculation_interval,
            alertForm.schedule_restriction,
            alertForm.skip_weekend,
            alertForm.config,
            creatingNewAlert,
        ]
    )

    const enabledAdvancedOptionsCount = useMemo(() => {
        let n = 0
        if (can_check_ongoing_interval && alertForm.config.check_ongoing_interval) {
            n += 1
        }
        if (
            (alertForm.calculation_interval === AlertCalculationInterval.DAILY ||
                alertForm.calculation_interval === AlertCalculationInterval.HOURLY) &&
            alertForm.skip_weekend
        ) {
            n += 1
        }
        if (quietHoursEnabled && (alertForm.schedule_restriction?.blocked_windows?.length ?? 0) > 0) {
            n += 1
        }
        return n
    }, [
        alertForm.calculation_interval,
        alertForm.config.check_ongoing_interval,
        alertForm.schedule_restriction?.blocked_windows?.length,
        alertForm.skip_weekend,
        can_check_ongoing_interval,
        quietHoursEnabled,
    ])

    return (
        <LemonModal onClose={handleClose} isOpen={isOpen} width={750} simple title="">
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
                            <LemonButton icon={<IconChevronLeft />} onClick={handleClose} size="xsmall" />

                            <h3>{creatingNewAlert ? 'New' : 'Edit '} Alert</h3>
                        </div>
                    </LemonModal.Header>

                    <LemonModal.Content>
                        <div className="deprecated-space-y-6">
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
                                    <UserActivityIndicator
                                        at={alert.created_at}
                                        by={alert.created_by}
                                        prefix="Created"
                                    />
                                ) : null}
                            </div>

                            <div className="deprecated-space-y-3">
                                <h3 className="mb-0">Definition</h3>
                                <div className="deprecated-space-y-3">
                                    {isBreakdownValid && (
                                        <LemonBanner type="warning">
                                            {alertMode === 'detector'
                                                ? 'For trends with breakdown, the detector will independently monitor each breakdown value (up to 25) and fire if any is anomalous.'
                                                : 'For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.'}
                                        </LemonBanner>
                                    )}
                                    <div className="flex gap-3 items-center">
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
                                                            : (alertSeries?.map(
                                                                  ({ custom_name, name, event }, index) => ({
                                                                      label: isBreakdownValid
                                                                          ? 'any breakdown value'
                                                                          : `${alphabet[index]} - ${
                                                                                custom_name ?? name ?? event
                                                                            }`,
                                                                      value: isBreakdownValid ? 0 : index,
                                                                  })
                                                              ) ?? [])
                                                    }
                                                    disabledReason={
                                                        isBreakdownValid &&
                                                        (alertMode === 'detector'
                                                            ? 'For trends with breakdown, the detector will independently monitor each breakdown value (up to 25) and fire if any is anomalous.'
                                                            : 'For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.')
                                                    }
                                                />
                                            </LemonField>
                                        </Group>
                                    </div>

                                    {anomalyDetectionEnabled && (
                                        <LemonSegmentedButton
                                            fullWidth
                                            value={alertMode}
                                            onChange={(value) => {
                                                if (value === 'detector') {
                                                    setAlertFormValue('detector_config', {
                                                        type: 'zscore',
                                                        threshold: 0.95,
                                                        window: getDefaultWindow(alertForm.calculation_interval),
                                                        preprocessing: { diffs_n: 1 },
                                                    })
                                                } else {
                                                    setAlertFormValue('detector_config', null)
                                                }
                                            }}
                                            options={[
                                                {
                                                    value: 'threshold',
                                                    label: 'Threshold',
                                                    tooltip:
                                                        'Alert when a value goes above or below a fixed threshold you define.',
                                                },
                                                {
                                                    value: 'detector',
                                                    label: 'Anomaly detection',
                                                    tooltip:
                                                        'Automatically detect unusual changes using AI (ohhh fancy, jk its just good old stats and ml stuff). No manual thresholds needed.',
                                                },
                                            ]}
                                        />
                                    )}

                                    {alertMode === 'threshold' ? (
                                        <div className="flex flex-wrap gap-x-3 gap-y-2 items-center">
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
                                    ) : (
                                        <DetectorSelector
                                            value={alertForm.detector_config ?? null}
                                            onChange={(config) => {
                                                setAlertFormValue('detector_config', config)
                                                clearSimulation()
                                                clearSimulationOverlay()
                                            }}
                                            calculationInterval={alertForm.calculation_interval}
                                        />
                                    )}

                                    {alertMode === 'detector' && alertForm.detector_config && (
                                        <div className="deprecated-space-y-2">
                                            <div className="flex gap-2 items-center">
                                                <h4 className="m-0">Simulation</h4>
                                                <LemonSelect
                                                    size="small"
                                                    data-attr="alertForm-simulate-range"
                                                    value={
                                                        simulationDateFrom ??
                                                        getDefaultSimulationRange(alertForm.calculation_interval)
                                                    }
                                                    onChange={(value) => setSimulationDateFrom(value)}
                                                    options={getSimulationRangeOptions(alertForm.calculation_interval)}
                                                />
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    data-attr="alertForm-simulate"
                                                    onClick={simulateAlert}
                                                    loading={simulationResultLoading}
                                                    tooltip="Run the detector on historical data to preview which points would be flagged as anomalies"
                                                >
                                                    Simulate
                                                </LemonButton>
                                            </div>
                                            {simulationResult && (
                                                <SimulationSummary
                                                    result={simulationResult}
                                                    detectorConfig={alertForm.detector_config}
                                                />
                                            )}
                                        </div>
                                    )}

                                    <div className="flex flex-wrap gap-x-3 gap-y-2 items-center">
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
                                            and check {alertForm?.config.check_ongoing_interval ? 'current' : 'last'}
                                        </div>
                                        <LemonSelect
                                            fullWidth
                                            className="w-28"
                                            data-attr="alertForm-trend-interval"
                                            disabledReason={
                                                <>
                                                    To change the interval being checked, edit and <b>save</b> the
                                                    interval which the insight is 'grouped by'
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
                                    {!creatingNewAlert && alert ? (
                                        <div className="text-sm text-muted flex flex-wrap items-center gap-x-2 gap-y-0">
                                            <IconClock
                                                className={`size-4 shrink-0 text-muted motion-reduce:animate-none${
                                                    !nextPlannedEvaluationStale && !alert.next_check_at
                                                        ? ' animate-spin'
                                                        : ''
                                                }`}
                                                aria-hidden
                                            />
                                            <span className="shrink-0">Next planned evaluation:</span>
                                            {nextPlannedEvaluationStale ? (
                                                <span>We'll recalculate this after you save.</span>
                                            ) : alert.next_check_at ? (
                                                <TZLabel time={alert.next_check_at} />
                                            ) : (
                                                <span>We're calculating this. This can take a few minutes.</span>
                                            )}
                                        </div>
                                    ) : null}
                                </div>
                            </div>

                            <div className="text-muted text-sm flex flex-wrap items-start gap-2">
                                <IconCalendar className="size-4 shrink-0 text-muted mt-0.5" aria-hidden />
                                <span className="min-w-0">
                                    Times use your project timezone ({projectTimezone}).{' '}
                                    <Link
                                        to={urls.settings('environment-customization', 'date-and-time')}
                                        target="_blank"
                                        targetBlankIcon={false}
                                    >
                                        Change in settings
                                    </Link>
                                </span>
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

                                <h4 className="mt-4">Destinations</h4>
                                <div className="mt-4">
                                    {inlineNotificationsEnabled ? (
                                        <InlineAlertNotifications alertId={alertId} />
                                    ) : alertId ? (
                                        <div className="flex flex-col">
                                            <AlertDestinationSelector
                                                alertId={alertId}
                                                insightShortId={insightShortId}
                                            />
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
                                            header: {
                                                type: enabledAdvancedOptionsCount > 0 ? 'primary' : 'tertiary',
                                                children: (
                                                    <span className="flex w-full min-w-0 items-center justify-between gap-2">
                                                        <span className="min-w-0">Advanced options</span>
                                                        {enabledAdvancedOptionsCount > 0 ? (
                                                            <span
                                                                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-current/20 bg-current/10 text-xs font-semibold tabular-nums leading-none"
                                                                aria-label={`${enabledAdvancedOptionsCount} advanced option${
                                                                    enabledAdvancedOptionsCount === 1 ? '' : 's'
                                                                } on`}
                                                            >
                                                                {enabledAdvancedOptionsCount}
                                                            </span>
                                                        ) : null}
                                                    </span>
                                                ),
                                            },
                                            content: (
                                                <div className="space-y-2">
                                                    <Group name={['config']}>
                                                        <div className="flex gap-1">
                                                            <LemonField name="check_ongoing_interval">
                                                                <LemonCheckbox
                                                                    checked={
                                                                        can_check_ongoing_interval &&
                                                                        alertForm?.config.check_ongoing_interval
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
                                                    {quietHoursEnabled ? (
                                                        <QuietHoursFields
                                                            scheduleRestriction={alertForm.schedule_restriction}
                                                            calculationInterval={alertForm.calculation_interval}
                                                            teamTimezone={projectTimezone}
                                                            onChange={(next) =>
                                                                setAlertFormValue('schedule_restriction', next)
                                                            }
                                                        />
                                                    ) : null}
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
                            disabledReason={!alertFormChanged && !hasPendingNotifications && 'No changes to save'}
                        >
                            {creatingNewAlert ? 'Create alert' : 'Save'}
                        </LemonButton>
                    </LemonModal.Footer>
                </Form>
            )}
        </LemonModal>
    )
}
