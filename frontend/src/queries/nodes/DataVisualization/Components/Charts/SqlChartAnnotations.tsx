import { AnnotationsLayer } from 'products/product_analytics/frontend/insights/trends/shared/AnnotationsLayer'

import { type SqlChartProps } from './SqlChart'
import { areConsecutiveDailyDates } from './sqlChartAnnotationDates'

/**
 * Renders the shared insight {@link AnnotationsLayer} over a quill SQL chart, reusing the exact
 * overlay product analytics trends use. Must be mounted as a child of the quill chart component so
 * it can read the chart layout via `useChartLayout()`.
 *
 * Annotations are date-anchored, so they only make sense when the x-axis column is a DATE/DATETIME.
 * We also require a saved insight id: annotations attach to an insight (or project/org scope), and
 * without a persisted insight there's nothing for insight-scoped annotations to hang off.
 */
export function SqlChartAnnotations({
    xData,
    insightNumericId,
    showAnnotations,
    inSharedMode,
}: SqlChartProps): JSX.Element | null {
    // inSharedMode matches the trends charts: shared/exported surfaces have no authenticated
    // session, so mounting the overlay there would hit the annotations API and fail.
    if (insightNumericId == null || showAnnotations === false || inSharedMode || !xData) {
        return null
    }

    // The overlay positions badges by whole-day offsets from the first point, so it is only
    // correct for daily, gap-free, ascending buckets. On any other cadence (monthly, hourly,
    // gaps, descending sorts) every badge would land on the wrong point, so render nothing.
    const isDateAxis = xData.column.type.name === 'DATE' || xData.column.type.name === 'DATETIME'
    if (!isDateAxis || !areConsecutiveDailyDates(xData.data)) {
        return null
    }

    return <AnnotationsLayer insightNumericId={insightNumericId} dates={xData.data} />
}
