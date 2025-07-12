import { LemonButton } from '@posthog/lemon-ui'

export enum ItemName {
    Tables = 'tables',
    Sources = 'sources',
}

interface PaginationControlsProps {
    hasMoreItems: boolean
    showAll: boolean
    onToggleShowAll: () => void
    totalCount: number
    itemName: ItemName
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
