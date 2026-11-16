import { IconSupport } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyHeader, EmptyTitle, IconStack, IconStackItem } from '@posthog/quill'

import type { TicketListEmptyKind } from './ticketListState'

export function QuillSupportTicketsEmptyState({
    kind,
    onSearchWithoutFilters,
}: {
    kind: TicketListEmptyKind
    onSearchWithoutFilters: () => void
}): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-support-light)">
                        <IconSupport />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>
                    {kind === 'search-with-filters'
                        ? 'No tickets match your search with the current filters applied.'
                        : 'No tickets'}
                </EmptyTitle>
            </EmptyHeader>
            {kind === 'search-with-filters' && (
                <EmptyContent>
                    <Button variant="outline" onClick={onSearchWithoutFilters}>
                        Search again without filters
                    </Button>
                </EmptyContent>
            )}
        </Empty>
    )
}
