import { LemonButton } from '@posthog/lemon-ui'

interface PaginationControlsProps {
    hasMoreItems: boolean
    showAll: boolean
    onToggleShowAll: () => void
    totalCount: number
    itemName: string // 'tables' or 'sources'
    maxItemsToShow: number
    additionalControls?: React.ReactNode
}

export function PaginationControls({
    hasMoreItems,
    showAll,
    onToggleShowAll,
    totalCount,
    itemName,
    maxItemsToShow,
    additionalControls,
}: PaginationControlsProps): JSX.Element {
    return (
        <div className="mb-4 flex justify-between items-center">
            {hasMoreItems && (
                <span className="text-muted text-sm">
                    {`Showing ${
                        showAll ? totalCount : Math.min(maxItemsToShow, totalCount)
                    } of ${totalCount} ${itemName}`}
                </span>
            )}
            <div className="flex items-center gap-2 ml-auto">
                {hasMoreItems && (
                    <LemonButton type="secondary" size="small" onClick={onToggleShowAll}>
                        {showAll ? 'Show less' : `Show all (${totalCount})`}
                    </LemonButton>
                )}
                {additionalControls}
            </div>
        </div>
    )
}
