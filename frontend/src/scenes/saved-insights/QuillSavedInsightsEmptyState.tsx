import { IconPlus, IconSearch } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

function emptyTitle(searchString: string | null, usingFilters: boolean): string {
    if (!usingFilters) {
        return 'There are no insights for this project.'
    }
    return searchString
        ? `There are no insights matching "${searchString}".`
        : 'There are no insights matching these filters.'
}

export function QuillSavedInsightsEmptyState({
    searchString,
    usingFilters,
    onClearSearch,
    onClearFilters,
}: {
    searchString: string | null
    usingFilters: boolean
    onClearSearch?: () => void
    onClearFilters?: () => void
}): JSX.Element {
    return (
        <Empty data-attr="insight-empty-state">
            <EmptyHeader>
                {usingFilters && (
                    <EmptyMedia variant="icon">
                        <IconSearch />
                    </EmptyMedia>
                )}
                <EmptyTitle>{emptyTitle(searchString, usingFilters)}</EmptyTitle>
                <EmptyDescription>
                    {usingFilters
                        ? 'Refine your keyword search, or try using other filters such as type, last modified or created by.'
                        : 'Once you create an insight, it will show up here.'}
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row justify-center">
                {onClearSearch && (
                    <Button variant="outline" onClick={onClearSearch}>
                        Clear search
                    </Button>
                )}
                {onClearFilters && (
                    <Button variant="outline" onClick={onClearFilters}>
                        Clear filters
                    </Button>
                )}
                {!usingFilters && (
                    <Button
                        variant="primary"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.insightNew()} />}
                        data-attr="add-insight-button-empty-state"
                    >
                        <IconPlus />
                        New insight
                    </Button>
                )}
            </EmptyContent>
        </Empty>
    )
}
