import { ReactNode } from 'react'

import { IconWarning } from '@posthog/icons'
import { Item, ItemContent, ItemFooter, ItemMedia, ItemTitle, Text } from '@posthog/quill'

/** A problem with saving, shown above the library or inspector with the actions that resolve it. */
export function CanvasBlocksNotice({
    tone,
    title,
    detail,
    children,
}: {
    tone: 'destructive' | 'warning'
    title: string
    detail: string
    children: ReactNode
}): JSX.Element {
    return (
        // Item drops a role prop, so the alert role sits on the wrapper.
        <div role="alert" className="shrink-0 px-3 pt-3">
            <Item
                variant="outline"
                size="xs"
                tone={tone}
                className="items-start"
                data-attr={`canvas-blocks-notice-${tone === 'destructive' ? 'error' : 'warning'}`}
            >
                <ItemMedia variant="icon" aria-hidden>
                    <IconWarning />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemTitle>{title}</ItemTitle>
                    {/* ItemDescription clamps to two lines, and this detail must show in full. */}
                    <Text size="xs" variant="muted" className="break-words">
                        {detail}
                    </Text>
                </ItemContent>
                <ItemFooter className="justify-start">
                    <div className="flex flex-wrap gap-2">{children}</div>
                </ItemFooter>
            </Item>
        </div>
    )
}
