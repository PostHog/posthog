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
    converted,
    experimentQuery,
}: {
    step: FunnelStepWithConversionMetrics
    converted: boolean
    experimentQuery: ExperimentQuery
}): void {
    const stepNo = step.order + 1
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
    // But the backend funnel query doesn't include this - it only has the actual metric events
    // Frontend: Step 0=Exposure, Step 1=$pageview, Step 2=uploaded_file
    // Backend:                  Step 1=$pageview, Step 2=uploaded_file
    // So we subtract 1 to map frontend -> backend step numbers
    const backendStepNo = stepNo - 1

    // Skip if trying to query the "Experiment exposure" step (doesn't exist in backend funnel)
    if (backendStepNo < 1) {
        return
    }

    // Create ExperimentActorsQuery (same pattern as FunnelsActorsQuery)
    const query: ExperimentActorsQuery = {
        kind: NodeKind.ExperimentActorsQuery,
        source: experimentQuery,
        funnelStep: converted ? backendStepNo : -backendStepNo, // Positive = converted, Negative = dropped off
        funnelStepBreakdown: variantKey, // Filter by variant
        includeRecordings: true,
    }

    // Open standard PersonsModal (same as regular funnels!)
    openPersonsModal({
        title,
        query,
        additionalSelect: { matched_recordings: 'matched_recordings' },
    })
}

export function StepBar({ step, stepIndex }: StepBarProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { showTooltip, hideTooltip } = useTooltip()
    const { experimentResult, experiment, experimentQuery } = useFunnelChartData()
    const { openModal } = useActions(sampledSessionsModalLogic)
    const hasActorsQueryFeature = useFeatureFlag('EXPERIMENT_FUNNEL_ACTORS_QUERY')

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
                converted: false, // Dropoffs
                experimentQuery,
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
                converted: true, // Conversions
                experimentQuery,
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
                        // - Step 0 with legacy: can use sampled sessions, show hint if sessionData exists
                        // - Step > 0 with new feature: can use actors query, show hint
                        // - Step > 0 with legacy: can use sampled sessions, show hint if sessionData exists
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
