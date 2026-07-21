import { LemonBanner } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { getDefaultAnomalyDetectorConfig } from 'products/alerts/frontend/logic/detectorConfigDefaults'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import {
    AlertSimulationResult,
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
} from 'products/alerts/frontend/types'
import { DetectorSelector } from 'products/alerts/frontend/views/DetectorSelector'

import { FunnelsDefinitionFields, HogQLDefinitionFields, TrendsDefinitionFields } from './AlertDefinitionFields'
import { AlertSimulationSection } from './AlertSimulationSection'
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
    alertMode: 'detector' | 'threshold'
    thresholdBoundsFormError?: string
    isNonTimeSeriesDisplay: boolean
    // Kind-specific inputs, grouped so the shared section only carries the bundle for the active kind.
    trends: TrendsDefinitionProps
    funnel: FunnelDefinitionProps
    hogql: HogQLDefinitionProps
    supportsAnomalyDetection: boolean
    twoColumnLayout?: boolean
    investigationAgentEnabled: boolean
    simulationResult: AlertSimulationResult | null
    simulationResultLoading: boolean
    simulationDateFrom: string | null
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
    /** Override the threshold row renderer. The legacy modal uses the inline wrapping row; the
     *  redesigned modal passes a stacked, labeled variant. Omit to keep the legacy row. */
    thresholdRowRenderer?: (props: ThresholdRowRenderProps) => JSX.Element
    onSimulateAlert: () => void
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
    twoColumnLayout = false,
    investigationAgentEnabled,
    simulationResult,
    simulationResultLoading,
    simulationDateFrom,
    onSetAlertFormValue,
    thresholdRowRenderer,
    onSimulateAlert,
    onSetSimulationDateFrom,
    onClearSimulation,
    onClearSimulationOverlay,
}: AlertDefinitionSectionProps): JSX.Element {
    // A steps funnel evaluates a single conversion-rate snapshot, so relative conditions have no prior
    // value to compare against. A historical-trend funnel is a time series, so it does support them.
    const isFunnelAlert = isFunnelsAlertConfig(alertForm.config)
    const supportsRelativeConditions = !isFunnelAlert || funnel.isTrendsFunnel
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
                <LemonBanner type="warning">
                    {alertMode === 'detector'
                        ? 'For trends with breakdown, the detector will independently monitor each breakdown value (up to 25) and fire if any is anomalous.'
                        : 'For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.'}
                </LemonBanner>
            )}
            <div
                className={
                    twoColumnLayout ? 'grid items-start gap-6 md:grid-cols-[minmax(0,55%)_minmax(0,1fr)]' : 'space-y-3'
                }
            >
                <div className="space-y-3">
                    {definitionFields}

                    {supportsAnomalyDetection && (
                        <LemonRadio
                            radioPosition="top"
                            value={alertMode}
                            onChange={(value) =>
                                onSetAlertFormValue(
                                    'detector_config',
                                    value === 'detector'
                                        ? getDefaultAnomalyDetectorConfig(alertForm.calculation_interval)
                                        : null
                                )
                            }
                            options={[
                                {
                                    value: 'threshold',
                                    label: 'Threshold',
                                    description: 'Alert when a value goes above or below a fixed value you set.',
                                    'data-attr': 'alertForm-mode-threshold',
                                },
                                {
                                    value: 'detector',
                                    label: 'Anomaly detection',
                                    description:
                                        'Automatically flag unusual changes using statistical models. No fixed value needed.',
                                    'data-attr': 'alertForm-mode-detector',
                                },
                            ]}
                        />
                    )}
                </div>

                <div className="space-y-3">
                    {alertMode === 'threshold' ? (
                        thresholdRowRenderer ? (
                            thresholdRowRenderer({
                                alertForm,
                                thresholdBoundsFormError,
                                isNonTimeSeriesDisplay,
                                supportsRelativeConditions,
                                onSetAlertFormValue,
                            })
                        ) : (
                            <ThresholdDefinitionRow
                                alertForm={alertForm}
                                thresholdBoundsFormError={thresholdBoundsFormError}
                                isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                                supportsRelativeConditions={supportsRelativeConditions}
                                onSetAlertFormValue={onSetAlertFormValue}
                            />
                        )
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
                </div>
            </div>
        </>
    )
}
