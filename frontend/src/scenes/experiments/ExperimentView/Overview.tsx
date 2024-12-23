import { useValues } from 'kea'

import { CachedExperimentFunnelsQueryResponse, CachedExperimentTrendsQueryResponse } from '~/queries/schema'
import { ExperimentIdType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function WinningVariantText({
    result,
    experimentId,
}: {
    result: CachedExperimentFunnelsQueryResponse | CachedExperimentTrendsQueryResponse
    experimentId: ExperimentIdType
}): JSX.Element {
    const { getIndexForVariant, getHighestProbabilityVariant } = useValues(experimentLogic)

    const highestProbabilityVariant = getHighestProbabilityVariant(result)
    const index = getIndexForVariant(result, highestProbabilityVariant || '')
    if (highestProbabilityVariant && index !== null && result) {
        const { probability } = result

        return (
            <div className="items-center inline-flex flex-wrap">
                <VariantTag experimentId={experimentId} variantKey={highestProbabilityVariant} />
                <span>&nbsp;is winning with a&nbsp;</span>
                <span className="font-semibold text-success items-center">
                    {`${(probability[highestProbabilityVariant] * 100).toFixed(2)}% probability`}&nbsp;
                </span>
                <span>of being best.&nbsp;</span>
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
    const { isPrimaryMetricSignificant, isSecondaryMetricSignificant } = useValues(experimentLogic)

    return (
        <div className="flex-wrap">
            <span>Your results are&nbsp;</span>
            <span className="font-semibold">
                {`${
                    isSecondary
                        ? isSecondaryMetricSignificant(metricIndex)
                        : isPrimaryMetricSignificant(metricIndex)
                        ? 'significant'
                        : 'not significant'
                }`}
                .
            </span>
        </div>
    )
}

export function Overview({ metricIndex = 0 }: { metricIndex?: number }): JSX.Element {
    const { experimentId, metricResults } = useValues(experimentLogic)

    const result = metricResults?.[metricIndex]
    if (!result) {
        return <></>
    }

    return (
        <div>
            <h2 className="font-semibold text-lg">Summary</h2>
            <div className="items-center inline-flex flex-wrap">
                <WinningVariantText result={result} experimentId={experimentId} />
                <SignificanceText metricIndex={metricIndex} />
            </div>
        </div>
    )
}
