import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { MenuActionList, type MenuParts } from '../../menu/MenuActionList'
import { useDashboardActions } from './useDashboardActions'

const DROPDOWN_PARTS: MenuParts = {
    Group: DropdownMenuGroup,
    Label: DropdownMenuLabel,
    Separator: DropdownMenuSeparator,
    Item: DropdownMenuItem,
    CheckboxItem: DropdownMenuCheckboxItem,
    Sub: DropdownMenuSub,
    SubTrigger: DropdownMenuSubTrigger,
    SubContent: DropdownMenuSubContent,
    RadioGroup: DropdownMenuRadioGroup,
    RadioItem: DropdownMenuRadioItem,
}

export function DashboardMenu(): JSX.Element | null {
    const actions = useDashboardActions()
    if (actions.length === 0) {
        return null
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button size="icon-sm" tooltip="More" aria-label="More" data-attr="dashboard-v2-menu">
                        <IconEllipsis />
                    </Button>
                }
            />
            <DropdownMenuContent align="end">
                <MenuActionList actions={actions} parts={DROPDOWN_PARTS} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
