import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'

import { CustomMenuProps } from '../types'

interface AddShortcutMenuItemProps extends CustomMenuProps {
    onClick: (e: React.MouseEvent<HTMLElement>) => void
    dataAttr: string
}

export function AddShortcutMenuItem({
    MenuItem = DropdownMenuItem,
    onClick,
    dataAttr,
}: AddShortcutMenuItemProps): JSX.Element {
    return (
        <MenuItem
            asChild
            onClick={(e) => {
                e.stopPropagation()
                onClick(e)
            }}
            data-attr={dataAttr}
        >
            <ButtonPrimitive menuItem>Add to shortcuts panel</ButtonPrimitive>
        </MenuItem>
    )
}
