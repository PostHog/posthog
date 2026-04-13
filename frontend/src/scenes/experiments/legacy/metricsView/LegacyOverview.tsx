import { useValues } from 'kea'

import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'

import {
    legacyGetHighestProbabilityVariant,
    legacyGetIndexForVariant,
} from '../calculations/legacyExperimentCalculations'
import { LegacyVariantTag } from '../components/LegacyVariantTag'

/**
 * @deprecated
 * These components support legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * For new experiments, use the modern Overview components.
 */
export function LegacyWinningVariantText({
    result,
}: {
    result:
        | CachedLegacyExperimentQueryResponse
        | CachedExperimentFunnelsQueryResponse
        | CachedExperimentTrendsQueryResponse
}): JSX.Element {
    const { getInsightType, experiment } = useValues(experimentLogic)

    const highestProbabilityVariant = legacyGetHighestProbabilityVariant(result)
    const index = legacyGetIndexForVariant(
        result,
        highestProbabilityVariant || '',
        getInsightType(experiment.metrics[0])
    )
    if (highestProbabilityVariant && index !== null && result) {
        const { probability } = result

        return (
            <div className="items-center inline-flex flex-wrap">
                <LegacyVariantTag variantKey={highestProbabilityVariant} />
                <span>&nbsp;is winning with a&nbsp;</span>
                <span className="font-semibold items-center">
                    {`${(probability[highestProbabilityVariant] * 100).toFixed(2)}% probability`}&nbsp;
                </span>
                <span>of being best.&nbsp;</span>
            </div>
        )
    }

    return <></>
}

/**
 * @deprecated
 * This component supports legacy experiment metrics.
 * For new experiments, use the modern SignificanceText component.
 */
export function LegacySignificanceText({
    metricUuid,
    isSecondary = false,
}: {
    metricUuid: string
    isSecondary?: boolean
}): JSX.Element {
    const { isPrimaryMetricSignificant, isSecondaryMetricSignificant } = useValues(experimentLogic)

    return (
        <div className="flex-wrap">
            <span>Your results are&nbsp;</span>
            <span className="font-semibold">
                {`${
                    (isSecondary ? isSecondaryMetricSignificant(metricUuid) : isPrimaryMetricSignificant(metricUuid))
                        ? 'significant'
                        : 'not significant'
                }`}
                .
            </span>
        </div>
    )
}
