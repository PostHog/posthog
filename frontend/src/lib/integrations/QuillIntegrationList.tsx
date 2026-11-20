import { ReactNode } from 'react'

import {
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemContent,
    ItemGroup,
} from '@posthog/quill'

export function QuillIntegrationList({
    isEmpty,
    emptyIcon,
    emptyTitle,
    emptyDescription,
    footer,
    children,
}: {
    isEmpty: boolean
    emptyIcon?: ReactNode
    emptyTitle: string
    emptyDescription: ReactNode
    footer?: ReactNode
    /** One `QuillIntegrationRow` per connection. */
    children: ReactNode
}): JSX.Element {
    return (
        <ItemGroup combined>
            {isEmpty ? (
                <Item variant="outline" size="sm" role="listitem">
                    <ItemContent>
                        <Empty>
                            <EmptyHeader>
                                {emptyIcon && <EmptyMedia variant="icon">{emptyIcon}</EmptyMedia>}
                                <EmptyTitle>{emptyTitle}</EmptyTitle>
                                <EmptyDescription>{emptyDescription}</EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    </ItemContent>
                </Item>
            ) : (
                children
            )}
            {footer && (
                <Item variant="outline" size="sm" role="listitem">
                    <ItemContent className="flex-row flex-wrap items-center gap-x-3 gap-y-2">{footer}</ItemContent>
                </Item>
            )}
        </ItemGroup>
    )
}
