import { urls } from 'scenes/urls'

import { Node, SavedInsightNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery, isSavedInsightNode } from '~/queries/utils'

export interface ChartOpenTarget {
    url: string
    label: string
}

/**
 * Where a report chart's open control points, and what to call it.
 *
 * The URL and the label are resolved together because `urls.insightNew` redirects a HogQL-backed
 * node to the SQL editor, so a single fixed label would describe the wrong destination for the SQL
 * charts a scout can attach.
 *
 * Pass the authored query, never the node `asEmbeddedChart` derives from it: that one carries
 * `embedded` and `showFilters: false`, which the insight scene honors, so the reader would land on
 * an insight with no filter bar and nothing to iterate with.
 */
export function chartOpenTarget(query: Node): ChartOpenTarget {
    // A `SavedInsightNode` holds a short id and no query of its own, so seeding a new insight from it
    // would open an empty editor. It resolves to the insight it already points at.
    if (isSavedInsightNode(query)) {
        return { url: urls.insightView((query as SavedInsightNode).shortId), label: 'Open insight' }
    }
    if (isDataVisualizationNode(query) && isHogQLQuery(query.source)) {
        return { url: urls.insightNew({ query }), label: 'Open in SQL editor' }
    }
    return { url: urls.insightNew({ query }), label: 'Open as new insight' }
}
