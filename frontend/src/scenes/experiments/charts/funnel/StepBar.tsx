import clsx from 'clsx'
import { useActions } from 'kea'
import { useRef } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { percentage } from 'lib/utils'

import {
    ExperimentActorsQuery,
    ExperimentQuery,
    isExperimentFunnelMetric,
    NodeKind,
    SessionData,
} from '~/queries/schema/schema-general'
import { getVariantColor } from '~/scenes/experiments/utils'
import { funnelTitle } from '~/scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal } from '~/scenes/trends/persons-modal/PersonsModal'
import type { Experiment } from '~/types'
import { FunnelStepWithConversionMetrics } from '~/types'

import { useTooltip } from './FunnelBarVertical'
import { useFunnelChartData } from './FunnelChart'
import { sampledSessionsModalLogic } from './sampledSessionsModalLogic'

export interface StepBarProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
}

interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}

/**
 * Opens the persons modal for a specific funnel step in an experiment.
 * Handles the step number mapping between frontend (with "Experiment exposure" step)
 * and backend (without exposure step).
 */
function openExperimentPersonsModalForSeries({
    step,
    stepIndex,
    converted,
    experimentQuery,
    experiment,
}: {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    converted: boolean
    experimentQuery: ExperimentQuery
    experiment: Experiment
}): void {
    const stepNo = stepIndex + 1
    const variantKey = step.breakdown_value as string

    // This should only be called for funnel metrics
    if (!isExperimentFunnelMetric(experimentQuery.metric)) {
        return
    }

    // Build title exactly like regular funnels (using frontend step numbering)
    const title = funnelTitle({
        converted,
        step: stepNo,
        breakdown_value: variantKey,
        label: step.name,
        order_type: experimentQuery.metric.funnel_order_type,
    })

    // IMPORTANT: For experiment funnels, the frontend adds an "Experiment exposure" step at index 0
    // But the backend actors query funnel doesn't include this - it only has the actual metric events
    // Frontend: Step 0=Exposure, Step 1=$pageview, Step 2=click
    // Backend:                  Step 1=$pageview, Step 2=click
    // So we map frontend step indices to backend step numbers directly (stepIndex = backendStepNo)
    const backendStepNo = stepIndex

    // Skip if trying to query the "Experiment exposure" step (stepIndex 0, doesn't exist in backend)
    if (backendStepNo < 1) {
        return
    }

    // Skip drop-off queries for the first metric step (stepIndex 1)
    // Drop-offs at step 1 would mean "exposed but never entered the funnel",
    // which can't be queried via the actors funnel (it starts at the first metric event)
    if (!converted && backendStepNo === 1) {
        return
    }

    // For drop-offs, the mapping is straightforward
    // Frontend step 2 drop-off = "completed step 1 ($pageview) but not step 2 (click)" = backend -2 = -stepIndex
    // Frontend step 3 drop-off = "completed step 2 (click) but not step 3 (next event)" = backend -3 = -stepIndex
    const funnelStep = converted ? backendStepNo : -backendStepNo

    // Create ExperimentActorsQuery with exposure configuration
    const query: ExperimentActorsQuery = {
        kind: NodeKind.ExperimentActorsQuery,
        source: experimentQuery,
        funnelStep,
        funnelStepBreakdown: variantKey, // Filter by variant
        includeRecordings: true,
        // Add exposure configuration from experiment
        exposureConfig: experiment?.exposure_criteria?.exposure_config || {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: '$feature_flag_called',
            properties: [],
        },
        multipleVariantHandling: experiment?.exposure_criteria?.multiple_variant_handling || 'exclude',
        featureFlagKey: experiment?.feature_flag?.key || '',
    }

    // Open standard PersonsModal (same as regular funnels!)
    openPersonsModal({
        title,
        query,
        additionalSelect: { matched_recordings: 'matched_recordings' },
    })
}

export function StepBar({ step, stepIndex }: StepBarProps): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { showTooltip, hideTooltip } = useTooltip()
    const { experimentResult, experiment, experimentQuery } = useFunnelChartData()
    const { openModal } = useActions(sampledSessionsModalLogic)
    const hasActorsQueryFeature = useFeatureFlag('EXPERIMENT_FUNNEL_ACTORS_QUERY')

    /**
     * bail if the experiment is not loaded. also, this serves as type guard for the experiment.
     */
    if (!experiment) {
        return null
    }

    const variantKey = Array.isArray(step.breakdown_value)
        ? step.breakdown_value[0]?.toString() || ''
        : step.breakdown_value?.toString() || ''

    const seriesColor =
        experiment?.parameters?.feature_flag_variants && variantKey
            ? getVariantColor(variantKey, experiment.parameters.feature_flag_variants)
            : 'var(--text-muted)'

    // Get sampled sessions from the experiment result
    let sessionData: SessionData[] | undefined
    if (experimentResult && variantKey) {
        if (variantKey === 'control') {
            sessionData = experimentResult.baseline.step_sessions?.[stepIndex]
        } else {
            const variantResult = experimentResult.variant_results?.find((v: any) => v.key === variantKey)
            sessionData = variantResult?.step_sessions?.[stepIndex] as SessionData[] | undefined
        }
    }
    // Legacy click handler for sampled sessions modal
    const handleLegacyClick = (): void => {
        if (sessionData) {
            openModal({
                sessionData,
                stepName: step.custom_name || step.name,
                variant: variantKey,
            })
        }
    }

    // New click handlers for actors query (with feature flag)
    const handleDropoffClick = (): void => {
        if (hasActorsQueryFeature && experimentQuery) {
            openExperimentPersonsModalForSeries({
                step: step,
                stepIndex: stepIndex,
                converted: false, // Dropoffs
                experimentQuery,
                experiment,
            })
        } else {
            // Fall back to legacy behavior
            handleLegacyClick()
        }
    }

    const handleConversionClick = (): void => {
        if (hasActorsQueryFeature && experimentQuery) {
            openExperimentPersonsModalForSeries({
                step: step,
                stepIndex: stepIndex,
                converted: true, // Conversions
                experimentQuery,
                experiment,
            })
        } else {
            // Fall back to legacy behavior
            handleLegacyClick()
        }
    }

    return (
        <>
            <div
                className={clsx('StepBar')}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={
                    {
                        '--series-color': seriesColor,
                        '--conversion-rate': percentage(step.conversionRates.fromBasisStep, 1, true),
                    } as StepBarCSSProperties
                }
                ref={ref}
                onMouseEnter={() => {
                    if (ref.current) {
                        const rect = ref.current.getBoundingClientRect()
                        // Only show "Click to inspect actors" hint when clicking will actually work:
                        // - Step 0 (exposure) with new feature enabled: can't use actors query (returns early), so don't show hint
                        // - Step 1 (first metric) drop-offs with new feature: can't query (no exposure in backend funnel), conversions work
                        // - Step 2+ with new feature: both conversions and drop-offs work
                        // - Legacy mode: show hint if sessionData exists
                        const hasClickableData = hasActorsQueryFeature ? stepIndex > 0 : !!sessionData
                        showTooltip([rect.x, rect.y, rect.width], stepIndex, step, hasClickableData)
                    }
                }}
                onMouseLeave={() => hideTooltip()}
            >
                <div
                    className="StepBar__backdrop"
                    onClick={handleDropoffClick}
                    style={{
                        cursor: hasActorsQueryFeature
                            ? stepIndex > 1
                                ? 'pointer'
                                : 'default'
                            : sessionData
                              ? 'pointer'
                              : 'default',
                    }}
                />
                <div
                    className="StepBar__fill"
                    onClick={handleConversionClick}
                    style={{
                        cursor: hasActorsQueryFeature
                            ? stepIndex > 0
                                ? 'pointer'
                                : 'default'
                            : sessionData
                              ? 'pointer'
                              : 'default',
                    }}
                />
            </div>
        </>
    )
}
