import { useValues } from 'kea'
import { useMemo } from 'react'

import { ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { SparklineData } from '../components/SparklineChart/SparklineChart'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from '../utils'

type NotUndefined<T> = T extends undefined ? never : T

function generateDataFromVolumeBuckets(
    volumeBuckets: NotUndefined<ErrorTrackingIssueAggregations['volume_buckets']>
): SparklineData {
    return volumeBuckets.map(({ label, value }) => ({
        value,
        date: new Date(label),
    }))
}

export function useSparklineData(
    aggregations: ErrorTrackingIssueAggregations | undefined,
    volumeResolution: number
): SparklineData {
    return useMemo(() => {
        if (aggregations?.volume_buckets) {
            return generateDataFromVolumeBuckets(aggregations.volume_buckets)
        }
        return new Array(volumeResolution).fill({ value: 0, date: new Date() })
    }, [aggregations, volumeResolution])
}

export function useSparklineDataIssueScene(): SparklineData {
    const { aggregations } = useValues(errorTrackingIssueSceneLogic)
    return useSparklineData(aggregations, ERROR_TRACKING_DETAILS_RESOLUTION)
}
