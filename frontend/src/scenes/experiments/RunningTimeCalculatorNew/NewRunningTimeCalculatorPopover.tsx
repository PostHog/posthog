import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type {
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { DEFAULT_MDE, experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { calculateExperimentTimeEstimate } from './calculations'

export interface NewRunningTimeCalculatorPopoverProps {
    experiment: Experiment
    tabId: string
}

export function NewRunningTimeCalculatorPopover({
    experiment,
    tabId,
}: NewRunningTimeCalculatorPopoverProps): JSX.Element {
    const { orderedPrimaryMetricsWithResults, primaryMetricsResultsLoading } = useValues(
        experimentLogic({ experimentId: experiment.id, tabId })
    )
    const { openRunningTimeConfigModal } = useActions(modalsLogic)

    if (primaryMetricsResultsLoading) {
        return (
            <div className="p-2">
                <div className="text-sm text-muted">Loading...</div>
            </div>
        )
    }

    const firstMetric = orderedPrimaryMetricsWithResults?.[0]
    if (!firstMetric?.metric || !firstMetric?.result?.baseline || !experiment.start_date) {
        return (
            <div className="p-2">
                <div className="text-sm text-muted">Waiting for results...</div>
            </div>
        )
    }

    const daysElapsed = dayjs().diff(dayjs(experiment.start_date), 'days', true)
    const variantExposures = firstMetric.result.variant_results.reduce(
        (sum: number, variant: ExperimentVariantResultFrequentist | ExperimentVariantResultBayesian) =>
            sum + variant.number_of_samples,
        0
    )
    const currentExposures = firstMetric.result.baseline.number_of_samples + variantExposures

    if (daysElapsed < 1 || currentExposures < 100) {
        return (
            <div className="p-2">
                <div className="text-sm text-muted">Gathering data...</div>
            </div>
        )
    }

    const mde = experiment.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
    const {
        currentExposures: exposures,
        recommendedSampleSize,
        exposureRate,
        estimatedRemainingDays,
    } = calculateExperimentTimeEstimate(firstMetric.metric, firstMetric.result, experiment, mde)

    if (estimatedRemainingDays === null) {
        return (
            <div className="p-2">
                <div className="text-sm text-muted">Waiting for results...</div>
            </div>
        )
    }

    return (
        <div className="p-2">
            <div className="flex items-start justify-between mb-2">
                {estimatedRemainingDays === 0 ? (
                    <div className="text-sm font-semibold">Ready to conclude</div>
                ) : (
                    <div className="text-sm font-semibold">
                        ~{Math.ceil(estimatedRemainingDays)} day{Math.ceil(estimatedRemainingDays) !== 1 ? 's' : ''}{' '}
                        remaining
                    </div>
                )}
                <LemonButton
                    size="xsmall"
                    icon={<IconGear />}
                    onClick={openRunningTimeConfigModal}
                    tooltip="Configure settings"
                />
            </div>
            <div className="text-xs text-muted space-y-1">
                <div>
                    Progress: {exposures?.toLocaleString()} / {recommendedSampleSize?.toLocaleString()} exposures
                </div>
                <div>Rate: ~{Math.round(exposureRate ?? 0).toLocaleString()} exposures/day</div>
            </div>
        </div>
    )
}
