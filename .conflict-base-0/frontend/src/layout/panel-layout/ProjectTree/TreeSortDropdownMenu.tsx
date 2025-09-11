import { IconSort } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItemIndicator,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { ProjectTreeSortMethod } from './projectTreeLogic'

interface SortDropdownProps {
    setSortMethod: (sortMethod: ProjectTreeSortMethod) => void
    sortMethod: ProjectTreeSortMethod
}

export function TreeSortDropdownMenu({ setSortMethod, sortMethod }: SortDropdownProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    iconOnly
                    data-attr="tree-sort-dropdown-menu-trigger-button"
                    tooltip={`Tree sorting: ${sortMethod === 'folder' ? 'Alphabetical' : 'Recently added'}`}
                    tooltipPlacement="bottom"
                >
                    <IconSort className="size-3 text-tertiary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                <DropdownMenuRadioGroup
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
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
