import { Item, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

export function GovernanceSectionFailed({ reason }: { reason: string }): JSX.Element {
    return (
        <Item variant="outline" tone="warning">
            <ItemContent>
                <ItemTitle>This section failed in the last scan. The next weekly scan tries again.</ItemTitle>
                <ItemDescription>{reason}</ItemDescription>
            </ItemContent>
        </Item>
    )
}
