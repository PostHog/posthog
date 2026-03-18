import { useValues } from 'kea'

import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
} from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { getHighestProbabilityVariant, getIndexForVariant } from '../legacyExperimentCalculations'
import { VariantTag } from './components'

export function WinningVariantText({
    result,
}: {
    result:
        | CachedLegacyExperimentQueryResponse
        | CachedExperimentFunnelsQueryResponse
        | CachedExperimentTrendsQueryResponse
}): JSX.Element {
    const { getInsightType, experiment } = useValues(experimentLogic)

    const highestProbabilityVariant = getHighestProbabilityVariant(result)
    const index = getIndexForVariant(result, highestProbabilityVariant || '', getInsightType(experiment.metrics[0]))
    if (highestProbabilityVariant && index !== null && result) {
        const { probability } = result

        return (
            <div className="items-center inline-flex flex-wrap">
                <VariantTag variantKey={highestProbabilityVariant} />
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

export function SignificanceText({
    metricUuid,
    isSecondary = false,
}: {
    metricUuid: string
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
                    (isSecondary ? isSecondaryMetricSignificant(metricUuid) : isPrimaryMetricSignificant(metricUuid))
                        ? 'significant'
                        : 'not significant'
                }`}
                .
            </span>
        </div>
    )
}

export function Overview({ metricUuid }: { metricUuid: string }): JSX.Element {
    const { legacyPrimaryMetricsResults, experiment } = useValues(experimentLogic)

    // Find metric index by UUID
    const index = experiment.metrics.findIndex((m) => m.uuid === metricUuid)
    const result = index >= 0 ? legacyPrimaryMetricsResults?.[index] : null
    if (!result) {
        return <></>
    }

    return (
        <div>
            <div className="items-center inline-flex flex-wrap">
                <WinningVariantText result={result} />
                <SignificanceText metricUuid={metricUuid} />
            </div>
        </div>
    )
}
