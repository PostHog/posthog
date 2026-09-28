import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { NavLinkSideActionButton } from '../../../NavLinkSideActionButton'

interface FlatNavProductMenuProps {
    icon: React.ReactNode
    tooltip: string
    'data-attr': string
    children: React.ReactNode
}

export function FlatNavProductMenu({
    icon,
    tooltip,
    'data-attr': dataAttr,
    children,
}: FlatNavProductMenuProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<NavLinkSideActionButton icon={icon} tooltip={tooltip} data-attr={dataAttr} />}
            />
            <DropdownMenuContent align="start" data-lemon-skin className="w-56">
                {children}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
