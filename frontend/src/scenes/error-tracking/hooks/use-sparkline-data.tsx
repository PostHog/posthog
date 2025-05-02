import { useValues } from 'kea'
import { useMemo } from 'react'

import { DateRange } from '~/queries/schema/schema-general'

import { SparklineData } from '../components/SparklineChart/SparklineChart'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { generateSparklineLabels } from '../utils'

export function useSparklineData(
    occurrences: number[] | undefined,
    dateRange: DateRange,
    volumeResolution: number
): SparklineData {
    return useMemo(() => {
        const labels = generateSparklineLabels(dateRange, volumeResolution)
        let values = occurrences
        if (!values) {
            values = new Array(volumeResolution).fill(0)
        }
        return values.map((value, index) => ({
            value,
            date: labels[index].toDate(),
        }))
    }, [occurrences, dateRange, volumeResolution])
}

export function useSparklineDataIssueScene(): SparklineData {
    const { aggregations, dateRange, volumeResolution } = useValues(errorTrackingIssueSceneLogic)
    return useSparklineData(aggregations?.volumeRange, dateRange, volumeResolution)
}
