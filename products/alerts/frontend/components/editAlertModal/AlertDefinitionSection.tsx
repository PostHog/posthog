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
import { AlertSimulationResult } from 'lib/components/Alerts/types'
import { DetectorSelector, getDefaultWindow } from 'lib/components/Alerts/views/DetectorSelector'
import { SimulationSummary } from 'lib/components/Alerts/views/SimulationSummary'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { alphabet } from 'lib/utils'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { getSimulationRangeOptions } from './editAlertModalUtils'

export interface AlertDefinitionSectionProps {
    alertForm: AlertFormType
    alertMode: 'detector' | 'threshold'
    isBreakdownValid: boolean
    isNonTimeSeriesDisplay: boolean
    alertSeries: Array<{ custom_name?: string | null; name?: string | null; event?: string | null }> | null
    formulaNodes: Array<{ formula: string; custom_name?: string | null }> | undefined
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

export function AlertDefinitionSection({
    alertForm,
    alertMode,
    isBreakdownValid,
    isNonTimeSeriesDisplay,
    alertSeries,
    formulaNodes,
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
    return (
        <>
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
