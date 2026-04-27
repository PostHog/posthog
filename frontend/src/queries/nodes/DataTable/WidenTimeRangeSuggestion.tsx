import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { DataTableNode, EventsQuery } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'

const SHORT_AFTER_VALUES = new Set(['-1h', '-30m', '-15m'])
const WIDER_AFTER = '-24h'

export interface WidenTimeRangeSuggestionProps {
    query: DataTableNode
    setQuery: (query: DataTableNode) => void
}

/**
 * On low-traffic projects the default 1-hour window for the Activity → Events scene
 * frequently returns nothing or times out at the database layer. This component renders
 * a one-click "Try last 24 hours" affordance alongside the empty/error state for those
 * queries — the workaround was previously only discoverable by manually opening the
 * date range picker.
 */
export function WidenTimeRangeSuggestion({ query, setQuery }: WidenTimeRangeSuggestionProps): JSX.Element | null {
    if (!isEventsQuery(query.source) || !SHORT_AFTER_VALUES.has(query.source.after ?? '')) {
        return null
    }

    return (
        <div className="flex flex-col items-center gap-2">
            <p className="text-sm text-tertiary m-0">
                Low-traffic projects often have nothing in the last hour — try a wider window.
            </p>
            <LemonButton
                type="primary"
                size="small"
                data-attr="widen-time-range-to-24h"
                onClick={() => {
                    setQuery({
                        ...query,
                        source: {
                            ...(query.source as EventsQuery),
                            after: WIDER_AFTER,
                        },
                    })
                }}
            >
                Try last 24 hours
            </LemonButton>
        </div>
    )
}
