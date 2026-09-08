import { IconCheck, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface SavedViewListItem {
    id: string
    name: string
}

export interface SavedViewsListProps<T extends SavedViewListItem> {
    views: T[]
    activeViewId?: string | null
    emptyMessage: string
    onSelect: (view: T) => void
    onDelete?: (view: T) => void
}

export function SavedViewsList<T extends SavedViewListItem>({
    views,
    activeViewId,
    emptyMessage,
    onSelect,
    onDelete,
}: SavedViewsListProps<T>): JSX.Element {
    if (views.length === 0) {
        return <div className="px-3 py-3 text-sm text-secondary">{emptyMessage}</div>
    }

    return (
        <div className="max-h-64 overflow-y-auto">
            {views.map((view) => (
                <div key={view.id} className="flex items-center">
                    <LemonButton
                        fullWidth
                        size="small"
                        type="tertiary"
                        className="min-w-0 justify-start rounded-none px-3 hover:!bg-fill-secondary"
                        sideIcon={activeViewId === view.id ? <IconCheck className="text-success" /> : null}
                        onClick={() => onSelect(view)}
                    >
                        <span className="truncate">{view.name}</span>
                    </LemonButton>
                    {onDelete && (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconTrash />}
                            tooltip={`Delete ${view.name}`}
                            aria-label={`Delete ${view.name}`}
                            onClick={() => onDelete(view)}
                        />
                    )}
                </div>
            ))}
        </div>
    )
}
