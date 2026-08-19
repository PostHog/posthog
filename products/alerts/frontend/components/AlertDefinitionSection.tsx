import { LemonBanner } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { AlertConditionType, ForecastConditionType } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { getDefaultAnomalyDetectorConfig } from 'products/alerts/frontend/logic/detectorConfigDefaults'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import { thresholdForConditionChange } from 'products/alerts/frontend/logic/thresholdPercent'
import {
    AlertMode,
    AlertSimulationResult,
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
} from 'products/alerts/frontend/types'
import { DetectorSelector } from 'products/alerts/frontend/views/DetectorSelector'
import { getDefaultForecastConfig, ForecastSelector } from 'products/alerts/frontend/views/ForecastSelector'

import {
    breakdownDisabledReason,
    FunnelsDefinitionFields,
    HogQLDefinitionFields,
    TrendsDefinitionFields,
} from './AlertDefinitionFields'
import { alertModeOptions } from './alertModeOptions'
import { AlertSimulationSection } from './AlertSimulationSection'
import { ForecastSimulationSection } from './ForecastSimulationSection'
import { InvestigationAgentSettings } from './InvestigationAgentSettings'
import { ThresholdDefinitionRow } from './ThresholdDefinitionRow'
import type { ThresholdRowRenderProps } from './ThresholdDefinitionRow'

export type { ThresholdRowRenderProps } from './ThresholdDefinitionRow'

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
    alertMode: AlertMode
    thresholdBoundsFormError?: string
    isNonTimeSeriesDisplay: boolean
    // Kind-specific inputs, grouped so the shared section only carries the bundle for the active kind.
    trends: TrendsDefinitionProps
    funnel: FunnelDefinitionProps
    hogql: HogQLDefinitionProps
    supportsAnomalyDetection: boolean
    supportsForecast: boolean
    insightInterval: IntervalType | null | undefined
    showAnomalyGuidance?: boolean
    twoColumnLayout?: boolean
    investigationAgentEnabled: boolean
    simulationResult: AlertSimulationResult | null
    simulationResultLoading: boolean
    forecastSimulationResultLoading: boolean
    simulationDateFrom: string | null
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
    /** Override the threshold row renderer. The legacy modal uses the inline wrapping row; the
     *  redesigned modal passes a stacked, labeled variant. Omit to keep the legacy row. */
    thresholdRowRenderer?: (props: ThresholdRowRenderProps) => JSX.Element
    onSimulateAlert: () => void
    onSimulateForecast: () => void
    onSetSimulationDateFrom: (value: string) => void
    onClearSimulation: () => void
    onClearSimulationOverlay: () => void
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
    supportsForecast,
    insightInterval,
    showAnomalyGuidance = false,
    twoColumnLayout = false,
    investigationAgentEnabled,
    simulationResult,
    simulationResultLoading,
    forecastSimulationResultLoading,
    simulationDateFrom,
    onSetAlertFormValue,
    thresholdRowRenderer,
    onSimulateAlert,
    onSimulateForecast,
    onSetSimulationDateFrom,
    onClearSimulation,
    onClearSimulationOverlay,
}: AlertDefinitionSectionProps): JSX.Element {
    // A steps funnel evaluates a single conversion-rate snapshot, so relative conditions have no prior
    // value to compare against. A historical-trend funnel is a time series, so it does support them.
    const isFunnelAlert = isFunnelsAlertConfig(alertForm.config)
    const supportsRelativeConditions = !isFunnelAlert || funnel.isTrendsFunnel
    const forecastUsesThresholdBounds =
        alertMode === 'forecast' && alertForm.forecast_config?.condition === ForecastConditionType.FUTURE_BREACH
    const showThresholdRow = alertMode === 'threshold' || forecastUsesThresholdBounds
    const thresholdRowProps: ThresholdRowRenderProps = {
        alertForm,
        thresholdBoundsFormError,
        isNonTimeSeriesDisplay,
        supportsRelativeConditions: supportsRelativeConditions && alertMode === 'threshold',
        onSetAlertFormValue,
    }
    let definitionFields: JSX.Element | null = null
    if (isTrendsAlertConfig(alertForm.config)) {
        definitionFields = (
            <TrendsDefinitionFields
                alertSeries={trends.alertSeries}
                formulaNodes={trends.formulaNodes}
                isBreakdownValid={trends.isBreakdownValid}
                alertMode={alertMode}
            />
        )
    } else if (isFunnelAlert) {
        definitionFields = (
            <FunnelsDefinitionFields
                alertForm={alertForm}
                stepLabels={funnel.stepLabels}
                funnelPreview={funnel.preview}
                isTrendsFunnel={funnel.isTrendsFunnel}
                showInlinePreview={!twoColumnLayout}
                onSetAlertFormValue={onSetAlertFormValue}
            />
        )
    } else if (isHogQLAlertConfig(alertForm.config)) {
        definitionFields = (
            <HogQLDefinitionFields
                alertForm={alertForm}
                hogqlPreview={hogql.preview}
                hogqlColumns={hogql.columns}
                hogqlValueColumnOptions={hogql.valueColumnOptions}
                hogqlLabelColumnOptions={hogql.labelColumnOptions}
                showInlinePreview={!twoColumnLayout}
                onSetAlertFormValue={onSetAlertFormValue}
            />
        )
    }

    return (
        <>
            {/* Trends-specific copy; funnels have their own breakdown messaging in the preview banner. */}
            {trends.isBreakdownValid && isTrendsAlertConfig(alertForm.config) && (
                <LemonBanner type="warning">{breakdownDisabledReason(alertMode)}</LemonBanner>
            )}
            <div
                className={
                    twoColumnLayout ? 'grid items-start gap-6 md:grid-cols-[minmax(0,55%)_minmax(0,1fr)]' : 'space-y-3'
                }
            >
                <div className="space-y-3">
                    {definitionFields}

                    {/* An existing forecast alert must keep its option even once the flag is off,
                        or the radio renders with nothing selected and the mode looks unset. */}
                    {(supportsAnomalyDetection || supportsForecast || alertMode === 'forecast') && (
                        <LemonRadio
                            radioPosition="top"
                            value={alertMode}
                            onChange={(value: AlertMode) => {
                                onSetAlertFormValue(
                                    'detector_config',
                                    value === 'detector'
                                        ? getDefaultAnomalyDetectorConfig(alertForm.calculation_interval)
                                        : null
                                )
                                onSetAlertFormValue(
                                    'forecast_config',
                                    value === 'forecast' ? getDefaultForecastConfig(insightInterval) : null
                                )
                                onClearSimulation()
                                onClearSimulationOverlay()
                                if (value === 'forecast') {
                                    onSetAlertFormValue('condition', { type: AlertConditionType.ABSOLUTE_VALUE })
                                    onSetAlertFormValue('threshold', {
                                        configuration: thresholdForConditionChange(
                                            alertForm.threshold.configuration,
                                            AlertConditionType.ABSOLUTE_VALUE,
                                            isFunnelAlert
                                        ),
                                    })
                                }
                            }}
                            options={alertModeOptions({
                                supportsAnomalyDetection,
                                supportsForecast: supportsForecast || alertMode === 'forecast',
                                showAnomalyGuidance,
                            })}
                        />
                    )}
                </div>

                <div className="space-y-3">
                    {alertMode === 'forecast' && (
                        <ForecastSelector
                            insightInterval={insightInterval}
                            value={alertForm.forecast_config ?? null}
                            onChange={(config) => {
                                onSetAlertFormValue('forecast_config', config)
                                onClearSimulation()
                                onClearSimulationOverlay()
                            }}
                        />
                    )}

                    {showThresholdRow ? (
                        thresholdRowRenderer ? (
                            thresholdRowRenderer(thresholdRowProps)
                        ) : (
                            <ThresholdDefinitionRow {...thresholdRowProps} />
                        )
                    ) : alertMode === 'detector' ? (
                        <DetectorSelector
                            value={alertForm.detector_config ?? null}
                            onChange={(config) => {
                                onSetAlertFormValue('detector_config', config)
                                onClearSimulation()
                                onClearSimulationOverlay()
                            }}
                            calculationInterval={alertForm.calculation_interval}
                        />
                    ) : null}

                    {alertMode === 'detector' && alertForm.detector_config && investigationAgentEnabled && (
                        <InvestigationAgentSettings alertForm={alertForm} onSetAlertFormValue={onSetAlertFormValue} />
                    )}

                    {alertMode === 'detector' && alertForm.detector_config && (
                        <AlertSimulationSection
                            alertForm={alertForm}
                            simulationResult={simulationResult}
                            simulationResultLoading={simulationResultLoading}
                            simulationDateFrom={simulationDateFrom}
                            onSimulateAlert={onSimulateAlert}
                            onSetSimulationDateFrom={onSetSimulationDateFrom}
                        />
                    )}

                    {alertMode === 'forecast' && alertForm.forecast_config && (
                        <ForecastSimulationSection
                            alertForm={alertForm}
                            insightInterval={insightInterval}
                            forecastSimulationResultLoading={forecastSimulationResultLoading}
                            simulationDateFrom={simulationDateFrom}
                            onSimulateForecast={onSimulateForecast}
                            onSetSimulationDateFrom={onSetSimulationDateFrom}
                        />
                    )}
                </div>
            </div>
        </>
    )
}
