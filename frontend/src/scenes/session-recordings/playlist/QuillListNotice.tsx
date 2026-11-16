import { ReactNode } from 'react'

import { Item, ItemContent } from '@posthog/quill'

export function QuillListNotice({
    tone,
    className,
    children,
}: {
    tone: 'warning' | 'destructive'
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <Item data-quill variant="outline" tone={tone} className={className}>
            <ItemContent className="text-sm">{children}</ItemContent>
        </Item>
    )
}
