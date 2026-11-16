import { ReactNode } from 'react'

import { DropdownMenuGroup, DropdownMenuLabel, DropdownMenuSeparator } from '@posthog/quill'

import { MENU_LABEL_ATTRIBUTE } from './useCollapseMenuRows'

type SceneActionsMenuGroupProps = {
    label: ReactNode
    children: ReactNode
}

export function SceneActionsMenuGroup({ label, children }: SceneActionsMenuGroupProps): JSX.Element {
    return (
        <DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuLabel {...{ [MENU_LABEL_ATTRIBUTE]: '' }}>{label}</DropdownMenuLabel>
            {children}
            <DropdownMenuSeparator />
        </DropdownMenuGroup>
    )
}
