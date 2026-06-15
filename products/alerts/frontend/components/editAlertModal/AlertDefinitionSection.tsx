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
import {
    AlertSimulationResult,
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
} from 'lib/components/Alerts/types'
import { DetectorSelector, getDefaultWindow } from 'lib/components/Alerts/views/DetectorSelector'
import { SimulationSummary } from 'lib/components/Alerts/views/SimulationSummary'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { alphabet } from 'lib/utils/strings'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { getSimulationRangeOptions } from './editAlertModalUtils'
import { HogQLAlertPreviewBanner, HogQLAlertPreviewRowsTable } from './HogQLAlertPreview'

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
    /** Result column names of the SQL insight, for the column pickers. */
    hogqlColumns: string[] | null
    /** Options for the evaluated-column picker (numeric columns, with fallbacks). */
    hogqlValueColumnOptions: { label: string; value: string }[]
    /** Options for the label-column picker (every column except the evaluated one). */
    hogqlLabelColumnOptions: { label: string; value: string }[]
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

/** Whether the form's SQL alert config is in any-row mode (every row checked, not just the last). */
function isHogQLAnyRow(alertForm: AlertFormType): boolean {
    return isHogQLAlertConfig(alertForm.config) && alertForm.config.evaluation === 'any_row'
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
    hogqlColumns,
    hogqlValueColumnOptions,
    hogqlLabelColumnOptions,
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
        (isFunnelAlert && 'Funnel alerts only support absolute value conditions') ||
        (isHogQLAnyRow(alertForm) &&
            "Rows in any-row mode aren't a time series — switch to 'the latest value' for relative conditions")
    const hogqlHasMultipleColumns = (hogqlColumns?.length ?? 0) > 1
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
                <>
                    <div className="flex gap-3 items-center">
                        <div>When</div>
                        <Group name={['config']}>
                            <LemonField name="evaluation" className="flex-auto">
                                {({ value, onChange }) => (
                                    <LemonSelect
                                        fullWidth
                                        data-attr="alertForm-hogql-evaluation"
                                        value={value ?? 'last_row'}
                                        onChange={(newValue) => {
                                            onChange(newValue)
                                            // Any-row mode checks unrelated rows — a relative condition is meaningless.
                                            if (newValue === 'any_row') {
                                                onSetAlertFormValue('condition', {
                                                    type: AlertConditionType.ABSOLUTE_VALUE,
                                                })
                                            }
                                        }}
                                        options={[
                                            {
                                                label: 'the last row',
                                                value: 'last_row',
                                                tooltip:
                                                    'For queries ordered oldest→newest (the usual chart order): the last row is the current value.',
                                            },
                                            {
                                                label: 'the first row',
                                                value: 'first_row',
                                                tooltip:
                                                    'For queries ordered newest→oldest (e.g. ORDER BY ... DESC): the first row is the current value. Pairs with a LIMIT to bound the query.',
                                            },
                                            {
                                                label: 'any row',
                                                value: 'any_row',
                                                tooltip:
                                                    'Every row is checked and the alert fires if any value breaches the threshold — e.g. one row per country.',
                                            },
                                        ]}
                                    />
                                )}
                            </LemonField>
                            {hogqlHasMultipleColumns && (
                                <LemonField name="column" className="flex-auto">
                                    {/* Prefilled with the last numeric column by alertFormLogic; the
                                        placeholder only shows when nothing numeric is detectable. */}
                                    <LemonSelect
                                        fullWidth
                                        data-attr="alertForm-hogql-column"
                                        placeholder="select column to evaluate"
                                        options={hogqlValueColumnOptions}
                                    />
                                </LemonField>
                            )}
                        </Group>
                    </div>
                    {isHogQLAnyRow(alertForm) && hogqlHasMultipleColumns && (
                        <div className="flex gap-3 items-center">
                            <Tooltip title="Names the breaching row in notifications and the check history.">
                                <div className="flex items-center gap-1">
                                    Labeled by <IconInfo className="text-muted" />
                                </div>
                            </Tooltip>
                            <Group name={['config']}>
                                <LemonField name="label_column" className="flex-auto">
                                    {/* Prefilled with the first non-evaluated column by alertFormLogic. */}
                                    <LemonSelect
                                        fullWidth
                                        data-attr="alertForm-hogql-label-column"
                                        placeholder="select label column"
                                        options={hogqlLabelColumnOptions}
                                    />
                                </LemonField>
                            </Group>
                        </div>
                    )}
                    <HogQLAlertPreviewBanner preview={hogqlPreview} conditionType={alertForm.condition?.type} />
                    {hogqlPreview?.status === 'ok' && <HogQLAlertPreviewRowsTable preview={hogqlPreview} />}
                </>
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
