import { Button, Text } from '@posthog/quill'

import { PaginationControlsProps } from './PaginationControls'

export function QuillPaginationControls({
    hasMoreItems,
    showAll,
    onToggleShowAll,
    totalCount,
    itemName,
    maxItemsToShow,
    additionalControls,
}: PaginationControlsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            {hasMoreItems && (
                <Text size="xs" variant="muted" render={<span />}>
                    {`Showing ${
                        showAll ? totalCount : Math.min(maxItemsToShow, totalCount)
                    } of ${totalCount} ${itemName}`}
                </Text>
            )}
            <div className="ms-auto flex flex-wrap items-center gap-2">
                {hasMoreItems && (
                    <Button variant="outline" onClick={onToggleShowAll}>
                        {showAll ? 'Show less' : `Show all (${totalCount})`}
                    </Button>
                )}
                {additionalControls}
            </div>
        </div>
    )
}
