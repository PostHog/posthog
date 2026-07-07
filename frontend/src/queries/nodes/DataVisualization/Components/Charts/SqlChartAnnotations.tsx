import { AnnotationsLayer } from 'products/product_analytics/frontend/insights/trends/shared/AnnotationsLayer'

import { LineGraphProps } from './LineGraph'

/**
 * Renders the shared insight {@link AnnotationsLayer} over a quill SQL chart, reusing the exact
 * overlay product analytics trends use. Must be mounted as a child of the quill chart component so
 * it can read the chart layout via `useChartLayout()`.
 *
 * Annotations are date-anchored, so they only make sense when the x-axis column is a DATE/DATETIME.
 * We also require a saved insight id: annotations attach to an insight (or project/org scope), and
 * without a persisted insight there's nothing for insight-scoped annotations to hang off.
 */
export function SqlChartAnnotations({ xData, insightNumericId, showAnnotations }: LineGraphProps): JSX.Element | null {
    if (insightNumericId == null || showAnnotations === false || !xData) {
        return null
    }

    const isDateAxis = xData.column.type.name === 'DATE' || xData.column.type.name === 'DATETIME'
    if (!isDateAxis) {
        return null
    }

    return <AnnotationsLayer insightNumericId={insightNumericId} dates={xData.data} />
}
