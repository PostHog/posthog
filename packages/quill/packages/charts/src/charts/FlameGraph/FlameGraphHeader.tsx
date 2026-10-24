import React from 'react'

import { formatShare } from './flame-colors'
import type { FlameSearchResult } from './flame-layout'

export interface FlameCrumb {
    key: string
    label: string
    onSelect: () => void
}

interface FlameGraphHeaderProps {
    /** From the root down to the focused node. Empty when the whole graph is in view. */
    crumbs: FlameCrumb[]
    /** Null when there is no zoom to reset. */
    onReset: (() => void) | null
    search: FlameSearchResult | null
}

/** Crumbs past this count collapse the middle into an ellipsis, keeping the root and the last two. */
const MAX_VISIBLE_CRUMBS = 3

const CRUMB_CLASS =
    'min-w-0 truncate bg-transparent border-0 p-0 cursor-pointer text-(--color-graph-axis-label) hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-(--color-graph-crosshair)'
const CURRENT_CRUMB_CLASS = 'min-w-0 truncate font-semibold'

function Crumb({
    label,
    current,
    onSelect,
}: {
    label: string
    current: boolean
    onSelect: (() => void) | null
}): React.ReactElement {
    if (current || !onSelect) {
        return (
            <span className={CURRENT_CRUMB_CLASS} title={label} data-attr="hog-chart-flame-breadcrumb">
                {label}
            </span>
        )
    }
    return (
        <button
            type="button"
            className={CRUMB_CLASS}
            title={label}
            onClick={onSelect}
            data-attr="hog-chart-flame-breadcrumb"
        >
            {label}
        </button>
    )
}

const Separator = (): React.ReactElement => (
    <span aria-hidden="true" className="shrink-0 text-(--color-graph-axis-label) opacity-60">
        ›
    </span>
)

function searchSummary(search: FlameSearchResult): string {
    if (search.count === 0) {
        return 'No matches'
    }
    return `${search.count.toLocaleString()} ${search.count === 1 ? 'match' : 'matches'} · ${formatShare(search.fraction)} of total`
}

export function FlameGraphHeader({ crumbs, onReset, search }: FlameGraphHeaderProps): React.ReactElement {
    const collapsed = crumbs.length > MAX_VISIBLE_CRUMBS
    const shown = collapsed ? [crumbs[0], ...crumbs.slice(-2)] : crumbs
    const hidden = collapsed ? crumbs.slice(1, -2) : []
    return (
        <div className="flex items-center gap-3 min-w-0 min-h-5 text-xs leading-5">
            <nav aria-label="Zoom path" className="flex items-center gap-1 min-w-0 flex-1 overflow-hidden">
                <Crumb label="All" current={crumbs.length === 0} onSelect={onReset} />
                {shown.map((crumb, i) => (
                    <React.Fragment key={crumb.key}>
                        <Separator />
                        {collapsed && i === 1 ? (
                            <>
                                <button
                                    type="button"
                                    className={`${CRUMB_CLASS} shrink-0`}
                                    title={hidden.map((c) => c.label).join(' › ')}
                                    onClick={hidden[hidden.length - 1].onSelect}
                                >
                                    …
                                </button>
                                <Separator />
                            </>
                        ) : null}
                        <Crumb label={crumb.label} current={i === shown.length - 1} onSelect={crumb.onSelect} />
                    </React.Fragment>
                ))}
            </nav>
            {search ? (
                <span
                    className="shrink-0 tabular-nums text-(--color-graph-axis-label)"
                    data-attr="hog-chart-flame-search-summary"
                >
                    {searchSummary(search)}
                </span>
            ) : null}
            {onReset ? (
                <button
                    type="button"
                    className={`${CRUMB_CLASS} shrink-0`}
                    onClick={onReset}
                    data-attr="hog-chart-flame-reset"
                >
                    Reset zoom
                </button>
            ) : null}
        </div>
    )
}
