import { IconWarning } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

/** The whole list failed to load, so the page offers one retry. */
export function QuillSupportTicketsLoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <Empty role="alert">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconWarning />
                </EmptyMedia>
                <EmptyTitle>Couldn't load tickets</EmptyTitle>
                <EmptyDescription>Check your connection, then try again.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" onClick={onRetry} data-attr="support-tickets-retry">
                    Try again
                </Button>
            </EmptyContent>
        </Empty>
    )
}
