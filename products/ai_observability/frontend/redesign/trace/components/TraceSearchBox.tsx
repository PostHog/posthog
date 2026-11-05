import { IconChevronDown, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { MatchDirection, TraceSearchFailure, TraceSearchStatus } from '../types'

export interface TraceSearchBoxData {
    query: string
    status: TraceSearchStatus
    total: number
    matchingSteps: number
    /** The 1-based place of the selected step among the matching steps, or null when it does not match. */
    position: number | null
    failure: TraceSearchFailure | null
}

export interface TraceSearchBoxProps extends TraceSearchBoxData {
    onQueryChange: (query: string) => void
    onStep: (direction: MatchDirection) => void
}

// The search API rejects longer queries.
const MAX_QUERY_LENGTH = 200

const FAILURES: Record<TraceSearchFailure, { label: string; tooltip: string }> = {
    too_slow: {
        label: 'Too large to search',
        tooltip: "Searching this trace took too long. Open a step and use the browser's find instead.",
    },
    failed: { label: 'Search failed', tooltip: 'Something went wrong. Try again in a moment.' },
}

function SearchStatus({ status, total, matchingSteps, position, failure }: TraceSearchBoxData): JSX.Element | null {
    if (status === 'idle') {
        return null
    }
    if (status === 'error') {
        const { label, tooltip } = FAILURES[failure ?? 'failed']
        return (
            <Tooltip title={tooltip}>
                <span className="flex shrink-0 items-center gap-1 text-xs text-danger">
                    <IconWarning className="shrink-0" />
                    <span>{label}</span>
                </span>
            </Tooltip>
        )
    }
    const text =
        status === 'loading'
            ? 'Searching…'
            : total === 0
              ? 'No matches'
              : `${position === null ? '' : `${position}/${matchingSteps} · `}${pluralize(total, 'match', 'matches')}`
    return (
        <span className="shrink-0 text-xs whitespace-nowrap text-secondary" aria-live="polite" translate="no">
            {text}
        </span>
    )
}

export function TraceSearchBox(props: TraceSearchBoxProps): JSX.Element {
    const { query, matchingSteps, onQueryChange, onStep } = props
    const disabledReason = matchingSteps === 0 ? 'No matching steps' : undefined
    return (
        <LemonInput
            type="search"
            size="small"
            className="w-80 max-w-full"
            placeholder="Search this trace"
            value={query}
            maxLength={MAX_QUERY_LENGTH}
            onChange={onQueryChange}
            onPressEnter={(event) => onStep(event.shiftKey ? 'previous' : 'next')}
            data-attr="trace-view-search-input"
            suffixAfterClear
            suffix={
                <span className="flex shrink-0 items-center gap-0.5">
                    <SearchStatus {...props} />
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronDown className="rotate-180" />}
                        onClick={() => onStep('previous')}
                        disabledReason={disabledReason}
                        tooltip="Previous match (Shift+Enter)"
                        aria-label="Previous match"
                        data-attr="trace-view-search-previous"
                    />
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronDown />}
                        onClick={() => onStep('next')}
                        disabledReason={disabledReason}
                        tooltip="Next match (Enter)"
                        aria-label="Next match"
                        data-attr="trace-view-search-next"
                    />
                </span>
            }
        />
    )
}
