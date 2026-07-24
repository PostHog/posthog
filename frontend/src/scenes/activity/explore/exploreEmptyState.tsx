import { LemonButton } from '@posthog/lemon-ui'

import { DataTableNode, Node } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isDataTableNode, isEventsQuery, isSessionsQuery } from '~/queries/utils'

const NARROW_DEFAULT_WINDOW = '-1h'
const WIDER_WINDOW = '-24h'

/**
 * Explore defaults to the last hour for performance. When that window is empty the generic
 * "no events" state reads like the project has no data at all — so tell the user the window is
 * just one hour and offer a one-click way to widen it before they give up.
 */
export function getExploreEmptyStateContext(
    query: Node,
    setQuery: (query: Node) => void
): Pick<QueryContext, 'emptyStateHeading' | 'emptyStateDetail'> {
    if (!isDataTableNode(query)) {
        return {}
    }

    const source = query.source
    const isNarrowDefaultWindow =
        (isEventsQuery(source) || isSessionsQuery(source)) && source.after === NARROW_DEFAULT_WINDOW
    if (!isNarrowDefaultWindow) {
        return {}
    }

    const noun = isSessionsQuery(source) ? 'sessions' : 'events'
    const widenedQuery: DataTableNode = { ...query, source: { ...source, after: WIDER_WINDOW } }
    return {
        emptyStateHeading: `No ${noun} in the last hour`,
        emptyStateDetail: (
            <div className="flex flex-col items-center gap-2">
                <span>This view only shows the last hour by default. There may be {noun} from earlier.</span>
                <LemonButton type="secondary" size="small" onClick={() => setQuery(widenedQuery)}>
                    Show last 24 hours
                </LemonButton>
            </div>
        ),
    }
}
