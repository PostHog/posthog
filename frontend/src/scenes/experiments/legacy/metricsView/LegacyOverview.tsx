import { useValues } from 'kea'

import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
    ExperimentFunnelsQuery,
    ExperimentTrendsQuery,
    ExperimentMetric,
} from '~/queries/schema/schema-general'
import {
    legacyGetHighestProbabilityVariant,
    legacyGetIndexForVariant,
    getInsightType,
    LegacyVariantTag,
    legacyExperimentLogic,
    getIsPrimaryMetricSignificant,
    getIsSecondaryMetricSignificant,
} from '~/scenes/experiments/legacy'

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
    const { experiment } = useValues(legacyExperimentLogic)

    const highestProbabilityVariant = legacyGetHighestProbabilityVariant(result)
    const index = legacyGetIndexForVariant(
        result,
        highestProbabilityVariant || '',
        getInsightType(experiment.metrics[0] as ExperimentTrendsQuery | ExperimentFunnelsQuery)
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
    const { experiment, legacyPrimaryMetricsResults, legacySecondaryMetricsResults } = useValues(legacyExperimentLogic)

    const isSecondaryMetricSignificant = getIsSecondaryMetricSignificant(legacySecondaryMetricsResults, experiment)
    const isPrimaryMetricSignificant = getIsPrimaryMetricSignificant(legacyPrimaryMetricsResults, experiment)

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

/**
 * @deprecated
 */
export function LegacyOverview({ metricUuid }: { metricUuid: string }): JSX.Element {
    const { legacyPrimaryMetricsResults, experiment } = useValues(legacyExperimentLogic)

    // Find metric index by UUID
    const index = experiment.metrics.findIndex(
        (m: ExperimentTrendsQuery | ExperimentFunnelsQuery | ExperimentMetric) => m.uuid === metricUuid
    )
    const result = index >= 0 ? legacyPrimaryMetricsResults?.[index] : null
    if (!result) {
        return <></>
    }

    return (
        <div>
            <div className="items-center inline-flex flex-wrap">
                <LegacyWinningVariantText result={result} />
                <LegacySignificanceText metricUuid={metricUuid} />
            </div>
        </div>
    )
}
