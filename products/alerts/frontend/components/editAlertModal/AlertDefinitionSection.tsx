import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    Tooltip,
} from '@posthog/lemon-ui'

import { AlertFormType, HogQLAlertPreview } from 'lib/components/Alerts/alertFormLogic'
import { AlertSimulationResult, isFunnelsAlertConfig, isTrendsAlertConfig } from 'lib/components/Alerts/types'
import { DetectorSelector, getDefaultWindow } from 'lib/components/Alerts/views/DetectorSelector'
import { SimulationSummary } from 'lib/components/Alerts/views/SimulationSummary'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { alphabet } from 'lib/utils/strings'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { getSimulationRangeOptions } from './editAlertModalUtils'

export interface AlertDefinitionSectionProps {
    alertForm: AlertFormType
    alertMode: 'detector' | 'threshold'
    thresholdBoundsFormError?: string
    isBreakdownValid: boolean
    isNonTimeSeriesDisplay: boolean
    alertSeries: Array<{ custom_name?: string | null; name?: string | null; event?: string | null }> | null
    formulaNodes: Array<{ formula: string; custom_name?: string | null }> | undefined
    /** Number of steps in the funnel, used to populate the step picker for funnel alerts. */
    funnelStepCount: number
    /** What a SQL alert would evaluate right now; null until the insight result loads. */
    hogqlPreview: HogQLAlertPreview | null
    anomalyDetectionEnabled: boolean
    investigationAgentEnabled: boolean
    simulationResult: AlertSimulationResult | null
    simulationResultLoading: boolean
    simulationDateFrom: string | null
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
    onSimulateAlert: () => void
    onSetSimulationDateFrom: (value: string) => void
    onClearSimulation: () => void
    onClearSimulationOverlay: () => void
}

/** Shows what the SQL alert would evaluate right now, surfacing shape problems before the first check. */
function HogQLAlertPreviewBanner({
    preview,
    conditionType,
}: {
    preview: HogQLAlertPreview | null
    conditionType?: AlertConditionType
}): JSX.Element {
    if (preview === null) {
        return (
            <LemonBanner type="info">
                This alert evaluates the last row of the SQL insight's single-column result.
            </LemonBanner>
        )
    }
    switch (preview.status) {
        case 'no-rows':
            return (
                <LemonBanner type="warning">
                    The query currently returns no rows — the alert will error until it returns at least one row.
                </LemonBanner>
            )
        case 'bad-shape':
            return (
                <LemonBanner type="warning">
                    The query result isn't plain rows of values — the alert requires a query returning a single numeric
                    column.
                </LemonBanner>
            )
        case 'multiple-columns':
            return (
                <LemonBanner type="warning">
                    This query returns {preview.columnCount} columns
                    {preview.columnNames ? ` (${preview.columnNames.join(', ')})` : ''}. The alert evaluates a single
                    numeric column — remove the extra columns (for example, don't select the date column) or the alert
                    will fail to evaluate.
                </LemonBanner>
            )
        case 'not-numeric':
            return (
                <LemonBanner type="warning">
                    The last row's value ({preview.value}) isn't a number — the alert requires a single numeric column.
                </LemonBanner>
            )
        case 'ok': {
            const isRelative =
                conditionType === AlertConditionType.RELATIVE_INCREASE ||
                conditionType === AlertConditionType.RELATIVE_DECREASE
            if (isRelative && preview.rowCount < 2) {
                return (
                    <LemonBanner type="warning">
                        Relative conditions compare the last two rows, but the query currently returns only one row.
                    </LemonBanner>
                )
            }
            return (
                <LemonBanner type="info">
                    The alert evaluates the last row of the result — currently{' '}
                    <strong>{humanFriendlyNumber(preview.currentValue)}</strong>
                    {isRelative && preview.previousValue !== null ? (
                        <>
                            {' '}
                            vs <strong>{humanFriendlyNumber(preview.previousValue)}</strong> in the previous row
                        </>
                    ) : null}{' '}
                    ({preview.rowCount} row{preview.rowCount === 1 ? '' : 's'}). Order the query chronologically so the
                    last row is the most recent value.
                </LemonBanner>
            )
        }
    }
}

export function AlertDefinitionSection({
    alertForm,
    alertMode,
    thresholdBoundsFormError,
    isBreakdownValid,
    isNonTimeSeriesDisplay,
    alertSeries,
    formulaNodes,
    funnelStepCount,
    hogqlPreview,
    anomalyDetectionEnabled,
    investigationAgentEnabled,
    simulationResult,
    simulationResultLoading,
    simulationDateFrom,
    onSetAlertFormValue,
    onSimulateAlert,
    onSetSimulationDateFrom,
    onClearSimulation,
    onClearSimulationOverlay,
}: AlertDefinitionSectionProps): JSX.Element {
    // Funnel alerts evaluate a single conversion-rate snapshot, so only absolute conditions apply.
    const isFunnelAlert = isFunnelsAlertConfig(alertForm.config)
    const relativeConditionDisabledReason =
        (isNonTimeSeriesDisplay && 'This condition is only supported for time series trends') ||
        (isFunnelAlert && 'Funnel alerts only support absolute value conditions')
    return (
        <>
            {isBreakdownValid && (
                <LemonBanner type="warning">
                    {alertMode === 'detector'
                        ? 'For trends with breakdown, the detector will independently monitor each breakdown value (up to 25) and fire if any is anomalous.'
                        : 'For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.'}
                </LemonBanner>
            )}
            {isTrendsAlertConfig(alertForm.config) ? (
                <div className="flex gap-3 items-center">
                    <div>When</div>
                    <Group name={['config']}>
                        <LemonField name="series_index" className="flex-auto">
                            <LemonSelect
                                fullWidth
                                data-attr="alertForm-series-index"
                                options={
                                    (formulaNodes?.length ?? 0) > 0
                                        ? (formulaNodes ?? []).map(({ formula, custom_name }, index) => ({
                                              label: `${custom_name ? custom_name : 'Formula'} (${formula})`,
                                              value: index,
                                          }))
                                        : (alertSeries?.map(({ custom_name, name, event }, index) => ({
                                              label: isBreakdownValid
                                                  ? 'any breakdown value'
                                                  : `${alphabet[index]} - ${custom_name ?? name ?? event}`,
                                              value: isBreakdownValid ? 0 : index,
                                          })) ?? [])
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
            ) : isFunnelsAlertConfig(alertForm.config) ? (
                <div className="flex flex-wrap gap-3 items-center">
                    <div>Alert on</div>
                    <Group name={['config']}>
                        <LemonField name="metric" className="flex-auto">
                            <LemonSelect
                                fullWidth
                                data-attr="alertForm-funnel-metric"
                                options={[
                                    { label: 'conversion from first step', value: 'conversion_from_start' },
                                    { label: 'conversion from previous step', value: 'conversion_from_previous' },
                                ]}
                            />
                        </LemonField>
                        <LemonField name="funnel_step" className="flex-auto">
                            <LemonSelect
                                fullWidth
                                data-attr="alertForm-funnel-step"
                                options={[
                                    { label: 'overall (last step)', value: null },
                                    ...Array.from({ length: funnelStepCount }, (_, index) => ({
                                        label: `step ${index + 1}`,
                                        value: index,
                                    })),
                                ]}
                            />
                        </LemonField>
                    </Group>
                </div>
            ) : (
                <HogQLAlertPreviewBanner preview={hogqlPreview} conditionType={alertForm.condition?.type} />
            )}

            {anomalyDetectionEnabled && (
                <LemonSegmentedButton
                    fullWidth
                    value={alertMode}
                    onChange={(value) => {
                        if (value === 'detector') {
                            onSetAlertFormValue('detector_config', {
                                type: 'zscore',
                                threshold: 0.95,
                                window: getDefaultWindow(alertForm.calculation_interval),
                                preprocessing: { diffs_n: 1 },
                            })
                        } else {
                            onSetAlertFormValue('detector_config', null)
                        }
                    }}
                    options={[
                        {
                            value: 'threshold',
                            label: 'Threshold',
                            tooltip: 'Alert when a value goes above or below a fixed threshold you define.',
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
                <div className="deprecated-space-y-2">
                    {thresholdBoundsFormError ? (
                        <LemonBanner type="error">{thresholdBoundsFormError}</LemonBanner>
                    ) : null}
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
                                            disabledReason: relativeConditionDisabledReason,
                                        },
                                        {
                                            label: 'decreases by',
                                            value: AlertConditionType.RELATIVE_DECREASE,
                                            disabledReason: relativeConditionDisabledReason,
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
                                    alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE &&
                                    alertForm.threshold.configuration.bounds?.lower
                                        ? alertForm.threshold.configuration.bounds?.lower * 100
                                        : alertForm.threshold.configuration.bounds?.lower
                                }
                                onChange={(value) =>
                                    onSetAlertFormValue('threshold', {
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
                                    alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE &&
                                    alertForm.threshold.configuration.bounds?.upper
                                        ? alertForm.threshold.configuration.bounds?.upper * 100
                                        : alertForm.threshold.configuration.bounds?.upper
                                }
                                onChange={(value) =>
                                    onSetAlertFormValue('threshold', {
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
                </div>
            ) : (
                <DetectorSelector
                    value={alertForm.detector_config ?? null}
                    onChange={(config) => {
                        onSetAlertFormValue('detector_config', config)
                        onClearSimulation()
                        onClearSimulationOverlay()
                    }}
                    calculationInterval={alertForm.calculation_interval}
                />
            )}

            {alertMode === 'detector' && alertForm.detector_config && investigationAgentEnabled && (
                <div className="deprecated-space-y-2">
                    <div className="flex items-center gap-1">
                        <h4 className="m-0">Investigation agent</h4>
                        <Tooltip
                            title="An optional AI agent that investigates anomaly fires against this insight's own data. It runs read-only HogQL queries, looks at the metric chart, and writes its findings — verdict, hypotheses, recommendations — to a notebook linked from the alert history. You can also have it gate notifications so false positives don't page you."
                            placement="right"
                            delayMs={0}
                        >
                            <IconInfo />
                        </Tooltip>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                        <LemonCheckbox
                            data-attr="alertForm-investigation-agent-enabled"
                            checked={!!alertForm.investigation_agent_enabled}
                            onChange={(checked) => onSetAlertFormValue('investigation_agent_enabled', checked)}
                            label={
                                <span className="flex items-center gap-1">
                                    Run investigation agent when this alert fires
                                    <Tooltip
                                        title="On the transition to firing, an agent validates the anomaly with read-only queries, writes a notebook with its findings, and links it from the alert check history. Runs once per transition."
                                        placement="right"
                                        delayMs={0}
                                    >
                                        <IconInfo />
                                    </Tooltip>
                                </span>
                            }
                        />
                        <LemonCheckbox
                            data-attr="alertForm-investigation-gates-notifications"
                            checked={!!alertForm.investigation_gates_notifications}
                            onChange={(checked) => onSetAlertFormValue('investigation_gates_notifications', checked)}
                            disabledReason={
                                !alertForm.investigation_agent_enabled
                                    ? 'Enable the investigation agent first'
                                    : undefined
                            }
                            label={
                                <span className="flex items-center gap-1">
                                    Wait for the verdict before notifying
                                    <Tooltip
                                        title="Notifications are delayed ~30–90s while the agent investigates. False-positive verdicts are suppressed. A safety-net task force-fires after a few minutes if the investigation stalls, so real fires can't be silently missed."
                                        placement="right"
                                        delayMs={0}
                                    >
                                        <IconInfo />
                                    </Tooltip>
                                </span>
                            }
                        />
                    </div>
                    {alertForm.investigation_agent_enabled && alertForm.investigation_gates_notifications && (
                        <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                            <span>On inconclusive verdict</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={alertForm.investigation_inconclusive_action ?? 'notify'}
                                onChange={(value) => onSetAlertFormValue('investigation_inconclusive_action', value)}
                                options={[
                                    {
                                        value: 'notify',
                                        label: 'Notify',
                                        tooltip: 'Safe default — an unsure agent is itself signal.',
                                    },
                                    {
                                        value: 'suppress',
                                        label: 'Suppress',
                                        tooltip: 'Only notify on true positives.',
                                    },
                                ]}
                            />
                        </div>
                    )}
                </div>
            )}

            {alertMode === 'detector' && alertForm.detector_config && (
                <div className="deprecated-space-y-2">
                    <div className="flex gap-2 items-center">
                        <h4 className="m-0">Simulation</h4>
                        <LemonSelect
                            size="small"
                            data-attr="alertForm-simulate-range"
                            value={simulationDateFrom ?? getDefaultSimulationRange(alertForm.calculation_interval)}
                            onChange={(value) => onSetSimulationDateFrom(value)}
                            options={getSimulationRangeOptions(alertForm.calculation_interval)}
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="alertForm-simulate"
                            onClick={onSimulateAlert}
                            loading={simulationResultLoading}
                            tooltip="Run the detector on historical data to preview which points would be flagged as anomalies"
                        >
                            Simulate
                        </LemonButton>
                    </div>
                    {simulationResult && (
                        <SimulationSummary result={simulationResult} detectorConfig={alertForm.detector_config} />
                    )}
                </div>
            )}
        </>
    )
}
