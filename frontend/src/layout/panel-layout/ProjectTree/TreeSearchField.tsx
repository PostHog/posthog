import { useActions, useValues } from 'kea'

import { IconCdCase, IconDocument, IconPlug, IconUser } from '@posthog/icons'

import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { fileSystemTypes } from '~/products'
import { FileSystemType } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { iconForType } from './defaultTree'
import { projectTreeLogic } from './projectTreeLogic'

const missingProductTypes: { value: string; label: string; icon?: React.ReactNode; flag?: string }[] = [
    { value: 'destination', label: 'Destinations', icon: <IconPlug /> },
    { value: 'site_app', label: 'Site apps', icon: <IconPlug /> },
    { value: 'source', label: 'Sources', icon: <IconPlug /> },
    { value: 'transformation', label: 'Transformations', icon: <IconPlug /> },
]

// TODO: This is a duplicate of TreeFiltersDropdownMenu.tsx
const productTypesMapped = [
    ...Object.entries(fileSystemTypes as unknown as Record<string, FileSystemType>).map(
        ([key, value]): { value: string; label: string; icon: React.ReactNode; flag?: string } => ({
            value: value.filterKey || key,
            label: value.name,
            icon: iconForType(value.iconType),
            flag: value.flag,
        })
    ),
    ...missingProductTypes,
]

interface TreeSearchFieldProps {
    root?: string
    placeholder?: string
}

export function TreeSearchField({ root, placeholder }: TreeSearchFieldProps): JSX.Element {
    const { panelTreeRef } = useValues(panelLayoutLogic)
    const { searchTerm } = useValues(projectTreeLogic)
    const { setSearchTerm, clearSearch } = useActions(projectTreeLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault() // Prevent scrolling
            const visibleItems = panelTreeRef?.current?.getVisibleItems()
            if (visibleItems && visibleItems.length > 0) {
                e.currentTarget.blur() // Remove focus from input
                panelTreeRef?.current?.focusItem(visibleItems[0].id)
            }
        }
    }

    return (
        <SearchAutocomplete
            inputPlaceholder={placeholder}
            includeNegation
            defaultValue={searchTerm}
            searchData={
                root === 'project://'
                    ? [
                          [
                              {
                                  value: 'user',
                                  label: 'user',
                                  hint: 'Search by user name',
                                  icon: <IconUser />,
                              },
                              [{ value: 'me', label: 'Me', hint: 'My stuff', icon: <IconUser /> }],
                              'enter a user, quotes are supported',
                          ],
                          [
                              {
                                  value: 'type',
                                  label: 'type',
                                  hint: 'Search by type',
                                  icon: <IconCdCase />,
                              },
                              productTypesMapped.filter(
                                  (productType) =>
                                      !productType.flag || featureFlags[productType.flag as keyof typeof featureFlags]
                              ),
                              'enter a type',
                          ],
                          [
                              {
                                  value: 'name',
                                  label: 'name',
                                  hint: 'Search by item name',
                                  icon: <IconDocument />,
                              },
                              undefined,
                              'enter a name, quotes are supported',
                          ],
                      ]
                    : undefined
            }
            onKeyDown={(e) => handleKeyDown(e)}
            onClear={() => clearSearch()}
            onChange={(value) => setSearchTerm(value)}
            autoFocus={true}
        />
    )
}
