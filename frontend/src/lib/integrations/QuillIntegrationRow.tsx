import { ReactNode } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

export function QuillIntegrationRow({
    icon,
    title,
    badges,
    meta,
    children,
    action,
}: {
    icon: ReactNode
    title: ReactNode
    badges?: ReactNode
    meta: ReactNode
    /** Extra content under the meta line, such as a repository summary or a notice. */
    children?: ReactNode
    action: ReactNode
}): JSX.Element {
    return (
        <Item variant="outline" size="sm" role="listitem" className="items-start">
            <ItemMedia variant="icon">{icon}</ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="flex flex-wrap items-center">
                    <span>{title}</span>
                    {badges}
                </ItemTitle>
                <ItemDescription>{meta}</ItemDescription>
                {children}
            </ItemContent>
            <ItemActions>{action}</ItemActions>
        </Item>
    )
}
