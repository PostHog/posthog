import { LemonButton } from '@posthog/lemon-ui'

import { dateFilterToText, dateStringToDayJs } from 'lib/utils'

import { DataTableNode, Node } from '~/queries/schema/schema-general'

// Offered as one-click ways to widen the search when a filtered query comes back empty.
const EXPANSION_WINDOWS: { after: string; label: string }[] = [
    { after: '-24h', label: 'Last 24 hours' },
    { after: '-7d', label: 'Last 7 days' },
    { after: '-30d', label: 'Last 30 days' },
]

// Only suggest windows that actually reach further back than the one currently applied.
export function widerWindows(currentAfter: string | undefined): { after: string; label: string }[] {
    if (!currentAfter) {
        return []
    }
    const currentStart = dateStringToDayJs(currentAfter)
    return EXPANSION_WINDOWS.filter(({ after }) => {
        if (after === currentAfter) {
            return false
        }
        const candidateStart = dateStringToDayJs(after)
        return !!candidateStart && (!currentStart || candidateStart.isBefore(currentStart))
    })
}

export function ActivityEmptyStateDetail({
    query,
    setQuery,
    noun,
}: {
    query: DataTableNode
    setQuery: (query: Node) => void
    noun: 'events' | 'sessions'
}): JSX.Element {
    const currentAfter = (query.source as { after?: string }).after
    const windowText = dateFilterToText(currentAfter ?? null, null, null)?.toLowerCase()
    const options = widerWindows(currentAfter)

    // Rendered inside a <p> by InsightEmptyState, so stick to phrasing content (spans, buttons) — no <div>.
    return (
        <span className="flex flex-col items-center gap-2">
            <span>
                {windowText
                    ? `Only ${noun} from the ${windowText} are shown — try a wider time range or change your filters.`
                    : 'Try changing the time range or your filters.'}
            </span>
            {options.length > 0 && (
                <span className="flex gap-2 flex-wrap justify-center">
                    {options.map(({ after, label }) => (
                        <LemonButton
                            key={after}
                            type="secondary"
                            size="small"
                            onClick={() => setQuery({ ...query, source: { ...query.source, after } })}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </span>
            )}
        </span>
    )
}
