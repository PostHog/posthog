import { Button, DropdownMenuItem } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

interface FlatNavMenuLinkItemProps {
    to?: string
    icon?: React.ReactNode
    children: React.ReactNode
}

export function FlatNavMenuLinkItem({ to, icon, children }: FlatNavMenuLinkItemProps): JSX.Element {
    return (
        <DropdownMenuItem render={<Button size="row" left render={<LinkPrimitive to={to} />} />}>
            {icon}
            <span className="truncate">{children}</span>
        </DropdownMenuItem>
    )
}
