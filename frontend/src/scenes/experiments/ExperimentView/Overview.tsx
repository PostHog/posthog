import { useValues } from 'kea'

import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { ExperimentIdType, ExperimentStatsMethod } from '~/types'

import { getHighestProbabilityVariant, getIndexForVariant } from '../experimentCalculations'
import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function WinningVariantText({
    result,
    experimentId,
}: {
    result:
        | CachedLegacyExperimentQueryResponse
        | CachedExperimentFunnelsQueryResponse
        | CachedExperimentTrendsQueryResponse
    experimentId: ExperimentIdType
}): JSX.Element {
    const { getInsightType, experiment, statsMethod } = useValues(experimentLogic)

    const highestProbabilityVariant = getHighestProbabilityVariant(result)
    const index = getIndexForVariant(result, highestProbabilityVariant || '', getInsightType(experiment.metrics[0]))
    if (highestProbabilityVariant && index !== null && result) {
        const { probability } = result
        const percentage = (probability[highestProbabilityVariant] * 100).toFixed(2)

        const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

        return (
            <div className="items-center inline-flex flex-wrap">
                <VariantTag experimentId={experimentId} variantKey={highestProbabilityVariant} />
                <span>&nbsp;is winning with a&nbsp;</span>
                <span className="font-semibold items-center">
                    {isBayesian ? `${percentage}% chance to win` : `${percentage}% probability`}&nbsp;
                </span>
                <span>{isBayesian ? '' : 'of being best.'}&nbsp;</span>
            </div>
        )
    }

    return <></>
}

export function SignificanceText({
    metricIndex,
    isSecondary = false,
}: {
    metricIndex: number
    isSecondary?: boolean
}): JSX.Element {
    /**
     * Remove this functions from the logic and make them pure so this component can be tested
     */
    const { isPrimaryMetricSignificant, isSecondaryMetricSignificant } = useValues(experimentLogic)

    return (
        <div className="flex-wrap">
            <span>Your results are&nbsp;</span>
            <span className="font-semibold">
                {`${
                    (isSecondary ? isSecondaryMetricSignificant(metricIndex) : isPrimaryMetricSignificant(metricIndex))
                        ? 'significant'
                        : 'not significant'
                }`}
                .
            </span>
        </div>
    )
}

export function Overview({ metricIndex = 0 }: { metricIndex?: number }): JSX.Element {
    const { experimentId, legacyPrimaryMetricsResults } = useValues(experimentLogic)

    const result = legacyPrimaryMetricsResults?.[metricIndex]
    if (!result) {
        return <></>
    }

    return (
        <div>
            <div className="items-center inline-flex flex-wrap">
                <WinningVariantText result={result} experimentId={experimentId} />
                <SignificanceText metricIndex={metricIndex} />
            </div>
        </div>
    )
}
