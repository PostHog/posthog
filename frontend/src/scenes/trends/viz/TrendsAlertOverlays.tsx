import { useValues } from 'kea'
import React, { useMemo } from 'react'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { ReferenceLines } from 'lib/hog-charts'

import type { InsightLogicProps } from '~/types'

import type { IndexedTrendResult } from '../types'
import { buildAnomalyMarkers } from './anomalyPointsAdapter'
import { AnomalyPointsLayer } from './AnomalyPointsLayer'
import { alertThresholdsToReferenceLines } from './goalLinesAdapter'

interface TrendsAlertOverlaysProps {
    insightId: number
    insightProps: InsightLogicProps
    indexedResults: IndexedTrendResult[] | undefined
    getColor: (r: IndexedTrendResult) => string
    isHidden: (r: IndexedTrendResult) => boolean
    getYAxisId: (r: IndexedTrendResult) => string
}

/** Renders alert threshold lines and anomaly point markers on top of the trends chart.
 *
 *  Lifted into its own component (rather than inlined in TrendsLineChartD3) so that
 *  insightAlertsLogic only mounts for saved insights — mounting it with `insightId: undefined`
 *  causes a spurious unfiltered alerts API call. The parent renders this only when
 *  `insight.id` is truthy. */
export function TrendsAlertOverlays({
    insightId,
    insightProps,
    indexedResults,
    getColor,
    isHidden,
    getYAxisId,
}: TrendsAlertOverlaysProps): React.ReactElement | null {
    const { alertThresholdLines, alertAnomalyPoints } = useValues(
        insightAlertsLogic({ insightId, insightLogicProps: insightProps })
    )

    const referenceLines = useMemo(() => alertThresholdsToReferenceLines(alertThresholdLines), [alertThresholdLines])

    const anomalyMarkers = useMemo(
        () => buildAnomalyMarkers(alertAnomalyPoints, indexedResults, getColor, getYAxisId, isHidden),
        [alertAnomalyPoints, indexedResults, getColor, getYAxisId, isHidden]
    )

    if (referenceLines.length === 0 && anomalyMarkers.length === 0) {
        return null
    }

    return (
        <>
            {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
            {anomalyMarkers.length > 0 && <AnomalyPointsLayer markers={anomalyMarkers} />}
        </>
    )
}
