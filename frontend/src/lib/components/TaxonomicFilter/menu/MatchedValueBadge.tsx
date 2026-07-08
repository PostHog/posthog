/**
 * "Matched on value" badge for taxonomic filter rows + preview pane.
 *
 * Some groups (log / resource attributes) search attribute *values* as well
 * as names via `search_values=true`. When a row surfaces because the query
 * matched one of its values — not the attribute name — the endpoint tags the
 * item with `matchedOn: 'value'` and the `matchedValue`. Surfacing it tells
 * the user why an attribute appears for a query that isn't in its name.
 */
import { Badge, cn, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { MenuFilterEntry } from './types'

const VALUE_MATCH_MAX_LENGTH = 30

export function getMatchedValue(entry: MenuFilterEntry): string | null {
    const item = entry.item as { matchedOn?: string; matchedValue?: string } | null
    if (item && item.matchedOn === 'value' && typeof item.matchedValue === 'string' && item.matchedValue.length > 0) {
        return item.matchedValue
    }
    return null
}

export function MatchedValueBadge({
    entry,
    className,
}: {
    entry: MenuFilterEntry
    className?: string
}): JSX.Element | null {
    const matchedValue = getMatchedValue(entry)
    if (!matchedValue) {
        return null
    }
    const truncated =
        matchedValue.length > VALUE_MATCH_MAX_LENGTH
            ? matchedValue.slice(0, VALUE_MATCH_MAX_LENGTH) + '…'
            : matchedValue
    return (
        <Tooltip>
            {/* Trigger must render a host element so base-ui's hover ref attaches —
                `Badge` is a plain component (not forwardRef). See VerificationBadge. */}
            <TooltipTrigger
                delay={300}
                render={(triggerProps) => (
                    <span {...triggerProps} className={cn('inline-flex min-w-0', className)}>
                        <Badge
                            variant="default"
                            aria-label="Matched on value"
                            data-attr="taxonomic-value-match-indicator"
                            className="max-w-48 shrink-0 truncate font-mono"
                        >
                            {truncated}
                        </Badge>
                    </span>
                )}
            />
            <TooltipContent className="max-w-64">Matched on value: "{matchedValue}"</TooltipContent>
        </Tooltip>
    )
}
