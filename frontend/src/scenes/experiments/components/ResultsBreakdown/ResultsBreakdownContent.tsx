import { useValues } from 'kea'

import {
    CachedExperimentQueryResponse,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantTrendsBaseStats,
} from '~/queries/schema/schema-general'
import { FunnelStep } from '~/types'

import { resultsBreakdownLogic } from './resultsBreakdownLogic'
import type { ResultBreakdownRenderProps } from './types'

const isExperimentVariantFunnels = (
    variant: ExperimentVariantTrendsBaseStats | ExperimentVariantFunnelsBaseStats
): variant is ExperimentVariantFunnelsBaseStats => {
    return 'success_count' in variant && 'failure_count' in variant
}

/**
 * we calculate the exposure difference between the metric results and the breakdown results.
 * we can get exposure count from the experiment logic or the metric results, but this may change in the future.
 *
 * If something fails, we return -1.
 */
const calculateExposureDifference = (
    result: CachedExperimentQueryResponse,
    breakdownResults: FunnelStep[][]
): number => {
    if (result.variants && breakdownResults) {
        const totalExposureCount = (
            result.variants as (ExperimentVariantTrendsBaseStats | ExperimentVariantFunnelsBaseStats)[]
        ).reduce((acc: number, variant: ExperimentVariantTrendsBaseStats | ExperimentVariantFunnelsBaseStats) => {
            if (isExperimentVariantFunnels(variant)) {
                return acc + variant.success_count + variant.failure_count
            }
            return acc + variant.count
        }, 0)

        const breakdownResultsTotalExposureCount = breakdownResults.reduce((acc, result) => {
            return acc + result[0].count
        }, 0)

        return totalExposureCount - breakdownResultsTotalExposureCount
    }

    return -1
}

export const ResultsBreakdownContent = ({
    result,
    children,
}: {
    result: CachedExperimentQueryResponse
    children?: (props: ResultBreakdownRenderProps) => JSX.Element | null
}): JSX.Element | null => {
    const { query, breakdownResults, breakdownResultsLoading } = useValues(resultsBreakdownLogic)

    const exposureDifference = calculateExposureDifference(result, breakdownResults as FunnelStep[][])

    /**
     * if `children` is a function, we call it with the query and breakdown results,
     * otherwise we return null.
     * children can narrow the props type to omit or make it non-nullable.
     *
     * This is the limit for a render prop. If we need to pass more props,
     * we should use a shared context with props.
     */
    return children && typeof children === 'function'
        ? children({ query, breakdownResults, breakdownResultsLoading, exposureDifference })
        : null
}
