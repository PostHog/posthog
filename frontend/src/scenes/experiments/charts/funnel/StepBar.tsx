import clsx from 'clsx'
import { useActions } from 'kea'
import { useRef } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { percentage } from 'lib/utils'

import {
    ExperimentActorsQuery,
    ExperimentQuery,
    InsightActorsQuery,
    isExperimentFunnelMetric,
    NodeKind,
    SessionData,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { getExposureConfigEventsNode } from '~/scenes/experiments/metricQueryUtils'
import { getVariantColor } from '~/scenes/experiments/utils'
import { funnelTitle } from '~/scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal } from '~/scenes/trends/persons-modal/PersonsModal'
import type { Experiment } from '~/types'
import { ChartDisplayType, FunnelStepWithConversionMetrics, PropertyFilterType, PropertyOperator } from '~/types'

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
 * Opens the persons modal for the experiment exposure step (step 0).
 * Queries the exposure event directly rather than using funnel actors query.
 */
function openExperimentPersonsModalForExposure({
    experimentQuery,
    variantKey,
    featureFlagKey,
    featureFlagVariants,
    exposureCriteria,
    startDate,
    endDate,
}: {
    experimentQuery: ExperimentQuery
    variantKey: string
    featureFlagKey: string
    featureFlagVariants: any[]
    exposureCriteria?: any
    startDate: string | null
    endDate: string | null
}): void {
    if (!isExperimentFunnelMetric(experimentQuery.metric)) {
        return
    }

    // Build the exposure event from experiment configuration
    // If exposure_criteria is empty or doesn't have an event, use the default $feature_flag_called
    const exposureConfig = exposureCriteria?.event ? exposureCriteria : { event: '$feature_flag_called' }
    const exposureEvent = getExposureConfigEventsNode(exposureConfig, {
        featureFlagKey,
        featureFlagVariants,
    })

    // Determine which property key to use for variant filtering
    const isDefaultExposure = exposureEvent.event === '$feature_flag_called'
    const variantPropertyKey = isDefaultExposure ? '$feature_flag' : `$feature/${featureFlagKey}`

    // Build a TrendsQuery with the exposure event, filtered by the specific variant
    // Use BoldNumber display type for total value aggregation (no day required)
    const trendsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: exposureEvent.kind,
                event: exposureEvent.event,
                custom_name: exposureEvent.custom_name,
                // Filter for the specific variant only
                properties: [
                    // Keep any existing properties that aren't variant filters
                    ...(exposureEvent.properties?.filter(
                        (p) => p.key !== `$feature/${featureFlagKey}` && p.key !== '$feature_flag'
                    ) || []),
                    // Add the variant filter
                    {
                        key: variantPropertyKey,
                        type: PropertyFilterType.Event,
                        value: isDefaultExposure ? featureFlagKey : variantKey,
                        operator: PropertyOperator.Exact,
                    },
                    // For default exposure, also filter by variant value
                    ...(isDefaultExposure
                        ? [
                              {
                                  key: '$feature_flag_response',
                                  type: PropertyFilterType.Event,
                                  value: variantKey,
                                  operator: PropertyOperator.Exact,
                              },
                          ]
                        : []),
                ],
            },
        ],
        dateRange: {
            date_from: startDate,
            date_to: endDate,
        },
        trendsFilter: {
            display: ChartDisplayType.BoldNumber,
        },
    }

    // Build InsightActorsQuery for the exposure event
    const actorsQuery: InsightActorsQuery = {
        kind: NodeKind.InsightActorsQuery,
        source: trendsQuery,
        includeRecordings: true,
    }

    openPersonsModal({
        title: `Experiment exposure • ${variantKey}`,
        query: actorsQuery,
        additionalSelect: { matched_recordings: 'matched_recordings' },
    })
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
        if (hasActorsQueryFeature && experimentQuery && experiment) {
            if (stepIndex === 0) {
                // Exposure step: query exposure event directly
                // Both dropoff and conversion show the same data (persons who were exposed)
                openExperimentPersonsModalForExposure({
                    experimentQuery,
                    variantKey,
                    featureFlagKey: experiment.feature_flag.key,
                    featureFlagVariants: experiment.parameters.feature_flag_variants,
                    exposureCriteria: experiment.exposure_criteria,
                    startDate: experiment.start_date,
                    endDate: experiment.end_date,
                })
            } else {
                // Regular steps: use funnel actors query
                openExperimentPersonsModalForSeries({
                    step: step,
                    stepIndex: stepIndex,
                    converted: false, // Dropoffs
                    experimentQuery,
                    experiment,
                })
            }
        } else {
            // Fall back to legacy behavior
            handleLegacyClick()
        }
    }

    const handleConversionClick = (): void => {
        if (hasActorsQueryFeature && experimentQuery && experiment) {
            if (stepIndex === 0) {
                // Exposure step: query exposure event directly
                // Both dropoff and conversion show the same data (persons who were exposed)
                openExperimentPersonsModalForExposure({
                    experimentQuery,
                    variantKey,
                    featureFlagKey: experiment.feature_flag.key,
                    featureFlagVariants: experiment.parameters.feature_flag_variants,
                    exposureCriteria: experiment.exposure_criteria,
                    startDate: experiment.start_date,
                    endDate: experiment.end_date,
                })
            } else {
                // Regular steps: use funnel actors query
                openExperimentPersonsModalForSeries({
                    step: step,
                    stepIndex: stepIndex,
                    converted: true, // Conversions
                    experimentQuery,
                    experiment,
                })
            }
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
                        // Show "Click to inspect actors" hint when clicking will work:
                        // - New feature enabled: works for all steps (including exposure)
                        // - Legacy: only show if sessionData exists
                        const hasClickableData = hasActorsQueryFeature || !!sessionData
                        showTooltip([rect.x, rect.y, rect.width], stepIndex, step, hasClickableData)
                    }
                }}
                onMouseLeave={() => hideTooltip()}
            >
                <div
                    className="StepBar__backdrop"
                    onClick={handleDropoffClick}
                    style={{
                        cursor: hasActorsQueryFeature || sessionData ? 'pointer' : 'default',
                    }}
                />
                <div
                    className="StepBar__fill"
                    onClick={handleConversionClick}
                    style={{
                        cursor: hasActorsQueryFeature || sessionData ? 'pointer' : 'default',
                    }}
                />
            </div>
        </>
    )
}
