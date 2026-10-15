import { Button, DropdownMenuItem } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

interface FlatNavMenuLinkItemProps {
    to?: string
    icon?: React.ReactNode
    'data-attr'?: string
    children: React.ReactNode
}

export function FlatNavMenuLinkItem({
    to,
    icon,
    'data-attr': dataAttr,
    children,
}: FlatNavMenuLinkItemProps): JSX.Element {
    return (
        <DropdownMenuItem render={<Button size="row" left render={<LinkPrimitive to={to} />} />} data-attr={dataAttr}>
            {icon}
            <span className="truncate">{children}</span>
        </DropdownMenuItem>
    )
}
