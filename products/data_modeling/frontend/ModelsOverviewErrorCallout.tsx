import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

export interface ModelsOverviewErrorCalloutProps {
    message: string
    onRetry: () => void
    dataAttr: string
}

export function ModelsOverviewErrorCallout({
    message,
    onRetry,
    dataAttr,
}: ModelsOverviewErrorCalloutProps): JSX.Element {
    return (
        <Item variant="outline" tone="destructive" data-attr={dataAttr}>
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onRetry}>
                    Try again
                </Button>
            </ItemActions>
        </Item>
    )
}
