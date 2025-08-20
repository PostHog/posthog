import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

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
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <div className={cn('mb-4 flex justify-between items-center', newSceneLayout && 'mb-0')}>
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
