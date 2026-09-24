import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { useTreeFilterMenuItems } from './useTreeFilterMenuItems'

interface FiltersDropdownProps {
    setSearchTerm: (searchTerm: string) => void
    searchTerm: string
}

export function TreeFiltersDropdownMenu({ setSearchTerm, searchTerm }: FiltersDropdownProps): JSX.Element {
    const items = useTreeFilterMenuItems(searchTerm, setSearchTerm)

    return (
        <LemonMenu items={items} placement="bottom-end">
            <LemonButton
                size="xsmall"
                icon={<IconFilter />}
                data-attr="tree-filters-dropdown-menu-trigger-button"
                tooltip="Tree filters"
                aria-label="Tree filters"
            />
        </LemonMenu>
    )
}
