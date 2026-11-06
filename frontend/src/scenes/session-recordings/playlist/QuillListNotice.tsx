import { ReactNode } from 'react'

import { Item, ItemContent } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

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
        <Item data-quill variant="outline" tone={tone} className={cn('w-auto', className)}>
            <ItemContent className="text-sm">{children}</ItemContent>
        </Item>
    )
}
