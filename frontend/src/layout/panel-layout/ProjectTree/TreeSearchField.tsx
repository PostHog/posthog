import { useActions, useValues } from 'kea'

import { IconCdCase, IconDocument, IconUser } from '@posthog/icons'

import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { projectTreeLogic } from './projectTreeLogic'
import { productTypesMapped } from './utils'

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
