import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Link, Spinner } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { SearchCategory, searchLogic } from 'lib/components/Search/searchLogic'
import { getCategoryDisplayName } from 'lib/components/Search/utils'
import { Label } from 'lib/ui/Label/Label'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'

const SEARCH_LOGIC_KEY = 'homepage'

export function HomepageSearchResults(): JSX.Element {
    const { query } = useValues(aiFirstHomepageLogic)
    const { allCategories, isSearching } = useValues(searchLogic({ logicKey: SEARCH_LOGIC_KEY }))
    const { setSearch } = useActions(searchLogic({ logicKey: SEARCH_LOGIC_KEY }))

    useEffect(() => {
        if (query) {
            setSearch(query)
        }
    }, [query, setSearch])

    const nonEmptyCategories = (allCategories as SearchCategory[]).filter((cat) => cat.items.length > 0)

    return (
        <ScrollableShadows direction="vertical" styledScrollbars className="flex-1 overflow-y-auto max-h-[60vh]">
            <div className="max-w-[640px] mx-auto w-full py-3">
                {isSearching && nonEmptyCategories.length === 0 && (
                    <div className="flex items-center justify-center py-8 gap-2 text-muted">
                        <Spinner className="size-3" />
                        <span>Searching...</span>
                    </div>
                )}

                {!isSearching && nonEmptyCategories.length === 0 && query && (
                    <div className="text-center text-muted py-8">
                        No results for &quot;<span className="italic">{query.trim()}</span>&quot;
                    </div>
                )}

                {nonEmptyCategories.map((group) => (
                    <div key={group.key} className="mb-4">
                        <Label className="px-3 mb-1" intent="menu">
                            {getCategoryDisplayName(group.key)}
                        </Label>
                        {group.items.map((item) => (
                            <div key={item.id} className="px-2">
                                <Link
                                    to={item.href}
                                    buttonProps={{ fullWidth: true }}
                                    className="flex items-center gap-2 px-2 py-1 rounded hover:bg-fill-button-tertiary-hover"
                                >
                                    {item.icon ? (
                                        item.icon
                                    ) : item.itemType ? (
                                        iconForType(item.itemType as FileSystemIconType)
                                    ) : (
                                        <span className="size-4" />
                                    )}
                                    <span className="truncate text-sm">{item.displayName || item.name}</span>
                                </Link>
                            </div>
                        ))}
                    </div>
                ))}
            </div>
        </ScrollableShadows>
    )
}
