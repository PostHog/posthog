import { ReactNode } from 'react'

import { DropdownMenuGroup, DropdownMenuLabel, DropdownMenuSeparator } from '@posthog/quill'

import { FLAT_MENU_LABEL_ATTRIBUTE } from './useCollapseFlatMenuRows'

type SceneFlatMenuGroupProps = {
    label?: ReactNode
    dataAttr?: string
    children: ReactNode
}

export function SceneFlatMenuGroup({ label, dataAttr, children }: SceneFlatMenuGroupProps): JSX.Element {
    return (
        <DropdownMenuGroup data-attr={dataAttr}>
            <DropdownMenuSeparator />
            {label != null && <DropdownMenuLabel {...{ [FLAT_MENU_LABEL_ATTRIBUTE]: '' }}>{label}</DropdownMenuLabel>}
            {children}
            <DropdownMenuSeparator />
        </DropdownMenuGroup>
    )
}
