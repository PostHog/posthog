import { useValues } from 'kea'
import React, { useMemo } from 'react'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
// TODO(hog-charts): transitional reach-back into scenes/trends. The IndexedTrendResult
// type and the buildAnomalyMarkers adapter need to move into hog-charts (or be replaced
// by a generic shape) before this overlay is reusable from non-trends call sites.
import type { IndexedTrendResult } from 'scenes/trends/types'
import { buildAnomalyMarkers } from 'scenes/trends/viz/trends-line-chart/anomalyPointsAdapter'

import type { InsightLogicProps } from '~/types'

import { ReferenceLines } from '../../overlays/ReferenceLine'
import { alertThresholdsToReferenceLines } from '../utils/goalLinesAdapter'
import { AnomalyPointsLayer } from './AnomalyPointsLayer'

interface AlertOverlayProps {
    insightId: number
    insightProps: InsightLogicProps
    indexedResults: IndexedTrendResult[] | undefined
    getColor: (r: IndexedTrendResult) => string
    isHidden: (r: IndexedTrendResult) => boolean
    getYAxisId: (r: IndexedTrendResult) => string
}

/** Renders alert threshold lines and anomaly point markers on top of the trends chart.
 *
 *  Lifted into its own component (rather than inlined in TrendsLineChart) so that
 *  insightAlertsLogic only mounts for saved insights — mounting it with `insightId: undefined`
 *  causes a spurious unfiltered alerts API call. The parent renders this only when
 *  `insight.id` is truthy. */
export function AlertOverlay({
    insightId,
    insightProps,
    indexedResults,
    getColor,
    isHidden,
    getYAxisId,
}: AlertOverlayProps): React.ReactElement | null {
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
