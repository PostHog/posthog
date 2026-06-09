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

    // IMPORTANT: For experiment funnels, the frontend adds an "Experiment exposure" step at index 0.
    // The backend actors query treats exposure as step 0 (returning all exposed actors) and the
    // actual metric events as steps 1..N, so frontend step indices map directly to backend steps.
    // Frontend: Step 0=Exposure, Step 1=$pageview, Step 2=click
    // Backend:  Step 0=Exposure, Step 1=$pageview, Step 2=click
    const backendStepNo = stepIndex

    // The exposure step (step 0) only supports conversions ("all exposed actors").
    // A drop-off "before exposure" is not a meaningful query.
    if (backendStepNo === 0 && !converted) {
        return
    }

    // For drop-offs, the mapping is straightforward (funnelStep = -stepIndex):
    // Step 1 drop-off = "exposed but did not reach the first metric event" = backend -1
    // Step 2 drop-off = "completed step 1 but not step 2 (click)" = backend -2
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

    // Source variants from the feature flag (the source of truth used by VariantTag and the rest
    // of the experiment UI). `parameters.feature_flag_variants` is an optional mirror that some
    // experiments never populate, which would otherwise leave the bars uncolored.
    const seriesColor =
        experiment.feature_flag?.filters.multivariate?.variants && variantKey
            ? getVariantColor(variantKey, experiment.feature_flag?.filters.multivariate?.variants)
            : 'var(--muted)'

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
                        // - Step 0 (exposure) with new feature enabled: conversion click returns all exposed actors
                        // - Step 1+ with new feature: both conversions and drop-offs work
                        // - Legacy mode: show hint if sessionData exists
                        const hasClickableData = hasActorsQueryFeature ? stepIndex >= 0 : !!sessionData
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
                            ? stepIndex > 0
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
                            ? stepIndex >= 0
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
