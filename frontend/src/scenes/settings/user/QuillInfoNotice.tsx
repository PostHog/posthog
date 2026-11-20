import { Item, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillInfoNotice({ children }: { children: string }): JSX.Element {
    return (
        <div className="ps-9">
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>{children}</ItemDescription>
                </ItemContent>
            </Item>
        </div>
    )
}
