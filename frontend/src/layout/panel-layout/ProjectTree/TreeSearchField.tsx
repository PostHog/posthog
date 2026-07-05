import { useActions, useValues } from 'kea'

import { IconCdCase, IconDocument, IconPlug, IconUser } from '@posthog/icons'

import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'
import { LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { fileSystemTypes } from '~/products'
import { FileSystemType } from '~/types'

import { iconForType } from './defaultTree'
import { projectTreeLogic } from './projectTreeLogic'

const missingProductTypes: { value: string; label: string; icon?: React.ReactNode; flag?: string }[] = [
    { value: 'destination', label: 'Destinations', icon: <IconPlug /> },
    { value: 'site_app', label: 'Web scripts', icon: <IconPlug /> },
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
    /** The tree this search field belongs to — ArrowDown moves focus into it. Multiple trees can be
     * mounted at once (panel switching keeps them alive), so a shared global ref would focus the
     * wrong, possibly hidden, tree. */
    treeRef: React.RefObject<LemonTreeRef>
}

export function TreeSearchField({ root, placeholder, treeRef }: TreeSearchFieldProps): JSX.Element {
    const { searchTerm } = useValues(projectTreeLogic)
    const { setSearchTerm, clearSearch } = useActions(projectTreeLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault() // Prevent scrolling
            const visibleItems = treeRef.current?.getVisibleItems()
            if (visibleItems && visibleItems.length > 0) {
                e.currentTarget.blur() // Remove focus from input
                treeRef.current?.focusItem(visibleItems[0].id)
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
