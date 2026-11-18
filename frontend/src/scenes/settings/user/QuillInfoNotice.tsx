import { Item, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillInfoNotice({ children }: { children: string }): JSX.Element {
    return (
        <Item tone="info" size="sm">
            <ItemContent>
                <ItemDescription>{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}
