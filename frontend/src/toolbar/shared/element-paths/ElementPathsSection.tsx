import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { pluralize } from 'lib/utils/strings'

import { ElementPathRow } from './ElementPathRow'
import { ElementPathsView, saveAsJourneyPath } from './elementPaths'
import type { ElementPathsResult } from './elementPathsApiTypes'

// The card stacks this section above the element's actions, so a long list would push them out of view.
const COLLAPSED_PATH_COUNT = 3

export interface ElementPathsSectionProps {
    view: ElementPathsView
    heading: JSX.Element
    className?: string
    /** Turns an app path into the URL that opens it in the project. */
    appUrl: (path: string) => string
    onSaveClick: (pathIndex: number) => void
    onRetry: () => void
}

/** The journeys section of the element card. Hidden until an element is selected, and for a project without user journeys. */
export function ElementPathsSection({
    view,
    heading,
    className,
    appUrl,
    onSaveClick,
    onRetry,
}: ElementPathsSectionProps): JSX.Element | null {
    const [expandedResult, setExpandedResult] = useState<ElementPathsResult | null>(null)

    if (view.status === 'idle' || view.status === 'unavailable') {
        return null
    }

    let body: JSX.Element
    if (view.status === 'loading') {
        body = (
            <div
                className="flex items-center gap-2 text-xs text-secondary"
                data-attr="toolbar-element-journeys-loading"
            >
                <Spinner className="shrink-0" />
                <span>Finding the most common paths through this element…</span>
            </div>
        )
    } else if (view.status === 'error') {
        body = (
            <div className="flex flex-col items-start gap-1 text-xs">
                <span>Couldn't load the paths through this element.</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={onRetry}
                    data-attr="toolbar-element-journeys-retry"
                >
                    Try again
                </LemonButton>
            </div>
        )
    } else if (view.status === 'no-clicks') {
        body = (
            <div className="flex flex-col gap-1 text-xs" data-attr="toolbar-element-journeys-no-clicks">
                <span className="font-semibold">{`No clicks ${view.rangeLabel}`}</span>
                <span className="text-secondary">
                    Autocapture may not record clicks on this element, or nobody uses it. An element that nobody uses
                    may be worth removing.
                </span>
            </div>
        )
    } else if (view.status === 'no-shared-path') {
        body = (
            <div className="flex flex-col gap-1 text-xs" data-attr="toolbar-element-journeys-no-shared-path">
                <span className="font-semibold">No shared path</span>
                <span className="text-secondary">
                    {`${pluralize(view.result.anchor_click_count, 'click')} from ${pluralize(
                        view.result.anchor_session_count,
                        'session'
                    )} ${view.rangeLabel}, but no two sessions took the same path through this element.`}
                </span>
            </div>
        )
    } else {
        const { result, rangeLabel } = view
        // Keyed on the result, so the list collapses again for the next element.
        const expanded = expandedResult === result
        const shownPaths = expanded ? result.paths : result.paths.slice(0, COLLAPSED_PATH_COUNT)
        const hiddenCount = result.paths.length - COLLAPSED_PATH_COUNT
        body = (
            <div className="flex flex-col gap-2 text-xs min-w-0" data-attr="toolbar-element-journeys-paths">
                <span className="text-secondary">
                    {`Most common paths ${rangeLabel}, from ${pluralize(
                        result.analyzed_session_count,
                        'session'
                    )} with a click on this element.`}
                </span>
                <ol className="flex flex-col gap-1.5 min-w-0">
                    {shownPaths.map((path, index) => (
                        <ElementPathRow
                            key={index}
                            path={path}
                            saveHref={appUrl(saveAsJourneyPath(path))}
                            onSaveClick={() => onSaveClick(index)}
                        />
                    ))}
                </ol>
                {hiddenCount > 0 && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => setExpandedResult(expanded ? null : result)}
                        data-attr="toolbar-element-journeys-show-more"
                    >
                        {expanded ? 'Show fewer paths' : `Show ${pluralize(hiddenCount, 'more path')}`}
                    </LemonButton>
                )}
                {shownPaths.some((path) => path.nodes.some((node) => !node.step_is_exact)) && (
                    <span className="text-secondary">
                        Steps with a dashed border are approximate. Check them in the journey form before you save.
                    </span>
                )}
            </div>
        )
    }

    return (
        <div className={className}>
            {heading}
            {body}
        </div>
    )
}
