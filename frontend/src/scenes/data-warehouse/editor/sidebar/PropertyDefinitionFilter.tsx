import { useState } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

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
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const hasActiveSearch = !!propertyDefinitionSearch
    const menuItems: LemonMenuItems = [
        {
            custom: true,
            label: () => (
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
                        onPressEnter={() => setIsMenuOpen(false)}
                    />
                </div>
            ),
        },
    ]

    return (
        <LemonMenu items={menuItems} visible={isMenuOpen} onVisibilityChange={setIsMenuOpen} closeOnClickInside={false}>
            <LemonButton
                type="tertiary"
                size="xsmall"
                noPadding
                active={isMenuOpen}
                tooltip="Filter properties"
                aria-label="Filter properties"
                stopPropagation
                className={cn('absolute right-0 z-10 -outline-offset-2', hasActiveSearch && 'text-accent')}
                icon={<IconSearch className={cn('size-3', hasActiveSearch ? 'text-accent' : 'text-tertiary')} />}
            />
        </LemonMenu>
    )
}
