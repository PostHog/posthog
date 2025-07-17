import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link/Link'
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { CustomMenuProps } from '../types'

export function ProductAnalyticsMenuItems({ MenuItem = DropdownMenuItem, onLinkClick }: CustomMenuProps): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)

    return (
        <>
            <DropdownMenuLabel>Create new insight type</DropdownMenuLabel>
            <DropdownMenuSeparator />

            {treeItemsNew
                .find(({ name }) => name === 'Insight')
                ?.children?.sort((a, b) => (a.visualOrder ?? 0) - (b.visualOrder ?? 0))
                ?.map((child) => (
                    <MenuItem
                        asChild
                        key={child.id}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                                // small delay to fight dropdown menu from taking focus
                                setTimeout(() => {
                                    mainContentRef?.current?.focus()
                                    onLinkClick?.(true)
                                }, 10)
                            }
                        }}
                    >
                        <Link
                            to={child.record?.href}
                            buttonProps={{ menuItem: true }}
                            onClick={() => {
                                onLinkClick?.(false)
                            }}
                        >
                            {child.icon}
                            {child.name}
                        </Link>
                    </MenuItem>
                ))}
        </>
    )
}
