import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { navigation3000Logic } from '../navigationLogic'
import { SidebarCategory } from '../types'
import { singularizeCategory } from './SidebarAccordion'

export function NewItemButton({ category }: { category: SidebarCategory }): JSX.Element | null {
    const { newItemCategory } = useValues(navigation3000Logic)
    const { initiateNewItemInCategory } = useActions(navigation3000Logic)

    if (!category.onAdd) {
        return null
    }
    return (
        <LemonButton
            icon={<IconPlus />}
            size="small"
            noPadding
            to={typeof category.onAdd === 'string' ? category.onAdd : undefined}
            onClick={(e) => {
                if (typeof category.onAdd === 'function') {
                    initiateNewItemInCategory(category.key)
                }
                e.stopPropagation()
            }}
            active={newItemCategory === category.key}
            tooltip={`New ${singularizeCategory(category.noun)}`}
            tooltipPlacement="bottom"
        />
    )
}
