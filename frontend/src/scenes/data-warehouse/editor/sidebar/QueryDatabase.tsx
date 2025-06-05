import { IconFolder, IconPlusSmall } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { useEffect, useRef } from 'react'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'

import { DatabaseSearchField } from './DatabaseSearchField'
import { queryDatabaseLogic } from './queryDatabaseLogic'

export const QueryDatabase = (): JSX.Element => {
    const { treeData, expandedFolders, expandedSearchFolders, searchTerm } = useValues(queryDatabaseLogic)
    const { setExpandedFolders, toggleFolderOpen, setTreeRef, setExpandedSearchFolders } =
        useActions(queryDatabaseLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    return (
        <div className="h-full">
            <div className="p-1">
                <DatabaseSearchField placeholder="Search database" />
            </div>
            <div className="h-full overflow-y-auto">
                <LemonTree
                    ref={treeRef}
                    data={treeData}
                    expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                    onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
                    onFolderClick={(folder, isExpanded) => {
                        if (folder) {
                            toggleFolderOpen(folder.id, isExpanded)
                        }
                    }}
                    renderItem={(item) => {
                        // Check if item has search matches for highlighting
                        const matches = item.record?.searchMatches
                        const hasMatches = matches && matches.length > 0

                        return (
                            <span className="truncate">
                                {hasMatches && searchTerm ? (
                                    <SearchHighlightMultiple
                                        string={item.name}
                                        substring={searchTerm}
                                        className="font-mono text-xs"
                                    />
                                ) : (
                                    <span className="truncate font-mono text-xs">{item.name}</span>
                                )}
                            </span>
                        )
                    }}
                    itemSideActionIcon={(item) => {
                        if (item.record?.type === 'sources') {
                            return (
                                <ButtonPrimitive
                                    iconOnly
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        router.actions.push(urls.dataPipelinesNew('source'))
                                    }}
                                >
                                    <IconPlusSmall className="text-tertiary" />
                                </ButtonPrimitive>
                            )
                        }
                    }}
                    renderItemIcon={(item) => {
                        if (item.record?.type === 'column') {
                            return <></>
                        }
                        return (
                            <TreeNodeDisplayIcon
                                item={item}
                                expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                                defaultNodeIcon={<IconFolder />}
                            />
                        )
                    }}
                />
            </div>
        </div>
    )
}
