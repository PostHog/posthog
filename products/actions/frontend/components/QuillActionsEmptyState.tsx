import { IconSearch } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

export function QuillActionsEmptyState({
    filtered,
    onClearFilters,
}: {
    /** True when a search or a filter hides every action. */
    filtered: boolean
    onClearFilters: () => void
}): JSX.Element {
    if (!filtered) {
        return (
            <Empty data-attr="actions-table-empty">
                <EmptyHeader>
                    <EmptyTitle>No actions yet.</EmptyTitle>
                    <EmptyDescription>Once you create an action, it will show up here.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <Empty data-attr="actions-table-empty">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconSearch />
                </EmptyMedia>
                <EmptyTitle>No actions match your search and filters.</EmptyTitle>
                <EmptyDescription>Try a different search, or clear the filters.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" onClick={onClearFilters}>
                    Clear search and filters
                </Button>
            </EmptyContent>
        </Empty>
    )
}
