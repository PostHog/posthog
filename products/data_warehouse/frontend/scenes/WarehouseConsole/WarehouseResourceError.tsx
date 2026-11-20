import { Button, Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

/** The error state of one section: it says what failed and offers a retry. */
export function WarehouseResourceError({
    title,
    onRetry,
    'data-attr': dataAttr,
}: {
    title: string
    onRetry: () => void
    'data-attr': string
}): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                <EmptyDescription>Check your connection and try again.</EmptyDescription>
            </EmptyHeader>
            <Button onClick={onRetry} data-attr={dataAttr}>
                Try again
            </Button>
        </Empty>
    )
}
