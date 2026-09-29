import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenuItemIndicator,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { ProjectTreeSortMethod } from './projectTreeLogic'

interface TreeSortMenuItemsProps {
    setSortMethod: (sortMethod: ProjectTreeSortMethod) => void
    sortMethod: ProjectTreeSortMethod
}

export function TreeSortMenuItems({ setSortMethod, sortMethod }: TreeSortMenuItemsProps): JSX.Element {
    return (
        <DropdownMenuRadioGroup
            aria-label="Sort files"
            value={sortMethod}
            onValueChange={(value) => setSortMethod(value as ProjectTreeSortMethod)}
        >
            <DropdownMenuRadioItem value="folder" asChild>
                <ButtonPrimitive menuItem data-attr="tree-filters-dropdown-menu-alphabetical-button">
                    <DropdownMenuItemIndicator intent="checkbox" />
                    Alphabetical
                </ButtonPrimitive>
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="recent" asChild>
                <ButtonPrimitive menuItem data-attr="tree-filters-dropdown-menu-recent-button">
                    <DropdownMenuItemIndicator intent="checkbox" />
                    Recently added
                </ButtonPrimitive>
            </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
    )
}
