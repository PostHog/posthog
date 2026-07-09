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

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { getDefaultAnomalyDetectorConfig } from 'lib/components/Alerts/detectorConfigDefaults'
import { FunnelAlertPreview } from 'lib/components/Alerts/funnelAlertPreview'
import { HogQLAlertPreview } from 'lib/components/Alerts/hogqlAlertPreview'
import { fractionToPercentInput, rescaleFunnelBound } from 'lib/components/Alerts/thresholdPercent'
import {
    AlertSimulationResult,
    isAnyRowHogQLConfig,
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
} from 'lib/components/Alerts/types'
import { DetectorSelector } from 'lib/components/Alerts/views/DetectorSelector'
import { SimulationSummary } from 'lib/components/Alerts/views/SimulationSummary'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { FunnelsDefinitionFields, HogQLDefinitionFields, TrendsDefinitionFields } from './AlertDefinitionFields'
import { getSimulationRangeOptions } from './editAlertModalUtils'

export interface TrendsDefinitionProps {
    /** Series in the alerted insight, for the series picker. */
    alertSeries: Array<{ custom_name?: string | null; name?: string | null; event?: string | null }> | null
    /** Formula nodes in the alerted insight, if any. */
    formulaNodes: Array<{ formula: string; custom_name?: string | null }> | undefined
    /** Whether the insight has a valid breakdown; drives the per-value monitoring banner. */
    isBreakdownValid: boolean
}

export interface FunnelDefinitionProps {
    /** Funnel step labels (real event/series names) for the conversion picker. */
    stepLabels: string[]
    /** Conversion rate(s) the alert would evaluate now; null until the result loads. */
    preview: FunnelAlertPreview | null
    /** A trends funnel alerts on the overall rate over time, so it skips the step picker. */
    isTrendsFunnel: boolean
}

export interface HogQLDefinitionProps {
    /** What a SQL alert would evaluate now; null until the result loads. */
    preview: HogQLAlertPreview | null
    /** Result column names, for the column pickers. */
    columns: string[] | null
    /** Evaluated-column picker options (numeric columns, with fallbacks). */
    valueColumnOptions: { label: string; value: string }[]
    /** Label-column picker options (every column except the evaluated one). */
    labelColumnOptions: { label: string; value: string }[]
}

export interface AlertDefinitionSectionProps {
    alertForm: AlertFormType
    alertMode: 'detector' | 'threshold'
    thresholdBoundsFormError?: string
    isNonTimeSeriesDisplay: boolean
    // Kind-specific inputs, grouped so the shared section only carries the bundle for the active kind.
    trends: TrendsDefinitionProps
    funnel: FunnelDefinitionProps
    hogql: HogQLDefinitionProps
    supportsAnomalyDetection: boolean
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
    return isAnyRowHogQLConfig(alertForm.config)
}

export function AlertDefinitionSection({
    alertForm,
    alertMode,
    thresholdBoundsFormError,
    isNonTimeSeriesDisplay,
    trends,
    funnel,
    hogql,
    supportsAnomalyDetection,
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
    // A steps funnel evaluates a single conversion-rate snapshot, so relative conditions have no prior
    // value to compare against. A historical-trend funnel is a time series, so it does support them.
    const isFunnelAlert = isFunnelsAlertConfig(alertForm.config)
    const supportsRelativeConditions = !isFunnelAlert || funnel.isTrendsFunnel
    const relativeConditionDisabledReason =
        (isNonTimeSeriesDisplay && 'This condition is only supported for time series trends') ||
        (isHogQLAnyRow(alertForm) &&
            "Rows in any-row mode aren't a time series — switch to 'the latest value' for relative conditions")
    return (
        <>
            {/* Trends-specific copy; funnels have their own breakdown messaging in the preview banner. */}
            {trends.isBreakdownValid && isTrendsAlertConfig(alertForm.config) && (
                <LemonBanner type="warning">
                    {alertMode === 'detector'
                        ? 'For trends with breakdown, the detector will independently monitor each breakdown value (up to 25) and fire if any is anomalous.'
                        : 'For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.'}
                </LemonBanner>
            )}
            {isTrendsAlertConfig(alertForm.config) ? (
                <TrendsDefinitionFields
                    alertSeries={trends.alertSeries}
                    formulaNodes={trends.formulaNodes}
                    isBreakdownValid={trends.isBreakdownValid}
                    alertMode={alertMode}
                />
            ) : isFunnelAlert ? (
                <FunnelsDefinitionFields
                    alertForm={alertForm}
                    stepLabels={funnel.stepLabels}
                    funnelPreview={funnel.preview}
                    isTrendsFunnel={funnel.isTrendsFunnel}
                    onSetAlertFormValue={onSetAlertFormValue}
                />
            ) : isHogQLAlertConfig(alertForm.config) ? (
                <HogQLDefinitionFields
                    alertForm={alertForm}
                    hogqlPreview={hogql.preview}
                    hogqlColumns={hogql.columns}
                    hogqlValueColumnOptions={hogql.valueColumnOptions}
                    hogqlLabelColumnOptions={hogql.labelColumnOptions}
                    onSetAlertFormValue={onSetAlertFormValue}
                />
            ) : null}

            {supportsAnomalyDetection && (
                <LemonSegmentedButton
                    fullWidth
                    value={alertMode}
                    onChange={(value) => {
                        if (value === 'detector') {
                            onSetAlertFormValue(
                                'detector_config',
                                getDefaultAnomalyDetectorConfig(alertForm.calculation_interval)
                            )
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
                                'Automatically detect unusual changes using statistical models. No fixed value threshold is required.',
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
                        {supportsRelativeConditions && (
                            <Group name={['condition']}>
                                <LemonField name="type">
                                    {({ value, onChange }) => (
                                        <LemonSelect
                                            fullWidth
                                            className="w-40"
                                            data-attr="alertForm-condition"
                                            value={value}
                                            onChange={(newType) => {
                                                onChange(newType)
                                                if (!isFunnelAlert) {
                                                    return
                                                }
                                                // Funnels have no #/% toggle: a relative condition uses a
                                                // PERCENTAGE threshold (0–1 fraction), "has value" an
                                                // ABSOLUTE one (raw percent). Keep the type in sync with the
                                                // condition and rescale the bounds so the on-screen number is
                                                // preserved across the switch instead of jumping ×100 / ÷100.
                                                const cfg = alertForm.threshold.configuration
                                                const targetType =
                                                    newType === AlertConditionType.ABSOLUTE_VALUE
                                                        ? InsightThresholdType.ABSOLUTE
                                                        : InsightThresholdType.PERCENTAGE
                                                if (cfg.type === targetType) {
                                                    return
                                                }
                                                onSetAlertFormValue('threshold', {
                                                    configuration: {
                                                        type: targetType,
                                                        bounds: {
                                                            lower: rescaleFunnelBound(cfg.bounds?.lower, targetType),
                                                            upper: rescaleFunnelBound(cfg.bounds?.upper, targetType),
                                                        },
                                                    },
                                                })
                                            }}
                                            options={[
                                                { label: 'has value', value: AlertConditionType.ABSOLUTE_VALUE },
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
                                    )}
                                </LemonField>
                            </Group>
                        )}
                        <div>less than</div>
                        <LemonField name="lower">
                            <LemonInput
                                type="number"
                                className="w-30"
                                data-attr="alertForm-lower-threshold"
                                suffix={isFunnelAlert ? <span aria-label="percent">%</span> : undefined}
                                value={
                                    alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                                        ? fractionToPercentInput(alertForm.threshold.configuration.bounds?.lower)
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
                                suffix={isFunnelAlert ? <span aria-label="percent">%</span> : undefined}
                                value={
                                    alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                                        ? fractionToPercentInput(alertForm.threshold.configuration.bounds?.upper)
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
                        {/* Funnels always compare as a percentage of the prior period, so the unit
                            toggle is hidden for them (the threshold is pinned to PERCENTAGE). */}
                        {!isFunnelAlert && alertForm.condition.type !== AlertConditionType.ABSOLUTE_VALUE && (
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
