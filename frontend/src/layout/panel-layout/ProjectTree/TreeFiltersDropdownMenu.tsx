import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { ProjectTreeLogicProps } from './projectTreeLogic'
import { useTreeFilterMenuItems } from './useTreeFilterMenuItems'

interface FiltersDropdownProps {
    logicProps: ProjectTreeLogicProps
}

export function TreeFiltersDropdownMenu({ logicProps }: FiltersDropdownProps): JSX.Element {
    const items = useTreeFilterMenuItems(logicProps)

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
