import { useActions } from 'kea'

import { DropdownMenuItem } from '@posthog/quill'

import { filterBarLogic } from './filterBarLogic'
import { FilterBarControl } from './filterBarTypes'

export function FilterBarControlItem({ control }: { control: FilterBarControl }): JSX.Element {
    const { setMenuOpen } = useActions(filterBarLogic)
    const Icon = control.icon
    return (
        <DropdownMenuItem
            onClick={() => {
                setMenuOpen(false)
                control.open()
            }}
            data-attr={`filter-bar-control-${control.id}`}
        >
            <Icon />
            {control.label}
        </DropdownMenuItem>
    )
}
