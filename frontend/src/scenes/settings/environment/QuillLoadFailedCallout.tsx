import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillLoadFailedCallout({
    message,
    onRetry,
    loading,
    className,
}: {
    message: string
    onRetry: () => void
    loading: boolean
    className?: string
}): JSX.Element {
    return (
        <Item tone="warning" size="sm" className={className}>
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onRetry} loading={loading}>
                    Try again
                </Button>
            </ItemActions>
        </Item>
    )
}
