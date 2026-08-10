import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useCloseDropdownMenu } from 'lib/ui/DropdownMenu/DropdownMenu'

import type { SidebarPropertyDefinitionTarget } from './queryDatabaseLogic'

export interface PropertyDefinitionFilterProps {
    propertyDefinitionKey: string
    propertyDefinitionSearch: string
    propertyDefinitionTarget: SidebarPropertyDefinitionTarget
    setPropertyDefinitionSearch: (
        propertyDefinitionKey: string,
        propertyDefinitionTarget: SidebarPropertyDefinitionTarget,
        search: string
    ) => void
}

export const PropertyDefinitionFilter = ({
    propertyDefinitionKey,
    propertyDefinitionSearch,
    propertyDefinitionTarget,
    setPropertyDefinitionSearch,
}: PropertyDefinitionFilterProps): JSX.Element => {
    const closeDropdownMenu = useCloseDropdownMenu()

    return (
        <div className="w-56 p-2" onKeyDown={(event) => event.stopPropagation()}>
            <LemonInput
                type="search"
                size="small"
                fullWidth
                autoFocus
                stopPropagation
                placeholder="Filter properties"
                value={propertyDefinitionSearch}
                onChange={(search) =>
                    setPropertyDefinitionSearch(propertyDefinitionKey, propertyDefinitionTarget, search)
                }
                onPressEnter={closeDropdownMenu}
            />
        </div>
    )
}
