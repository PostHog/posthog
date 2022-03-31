import React from 'react'
import { Tag } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { universalSearchLogic } from './universalSearchLogic'
import { searchListLogic } from 'lib/components/UniversalSearch/searchListLogic'
import { SearchList } from 'lib/components/UniversalSearch/searchList'
import { UniversalSearchGroupType, UniversalSearchLogicProps } from './types'
import clsx from 'clsx'

export interface SearchResultsProps {
    focusInput: () => void
    universalSearchLogicProps: UniversalSearchLogicProps
}

function CategoryPill({
    isActive,
    groupType,
    universalSearchLogicProps,
    onClick,
}: {
    isActive: boolean
    groupType: UniversalSearchGroupType
    universalSearchLogicProps: UniversalSearchLogicProps
    onClick: () => void
}): JSX.Element {
    const logic = searchListLogic({ ...universalSearchLogicProps, listGroupType: groupType })
    const { searchGroups } = useValues(universalSearchLogic)
    const { totalResultCount } = useValues(logic)

    const group = searchGroups.find((g) => g.type === groupType)
    const canInteract = totalResultCount > 0

    return (
        <Tag
            data-attr={`taxonomic-tab-${groupType}`}
            className={clsx({ 'taxonomic-pill-active': isActive, 'taxonomic-count-zero': !canInteract })}
            onClick={canInteract ? onClick : undefined}
        >
            {group?.name}
            {': '}
            {totalResultCount ?? '...'}
        </Tag>
    )
}

export function SearchResults({ focusInput, universalSearchLogicProps }: SearchResultsProps): JSX.Element {
    const { activeTab, searchGroups, searchGroupTypes } = useValues(universalSearchLogic)
    const { setActiveTab } = useActions(universalSearchLogic)

    if (searchGroupTypes.length === 1) {
        return (
            <BindLogic
                logic={searchListLogic}
                props={{ ...universalSearchLogicProps, listGroupType: searchGroupTypes[0] }}
            >
                <SearchList />
            </BindLogic>
        )
    }

    const openTab = activeTab || searchGroups[0].type
    return (
        <>
            <div className={'taxonomic-group-title'}>Categories</div>
            <div className={'taxonomic-pills'}>
                {searchGroupTypes.map((groupType) => {
                    return (
                        <CategoryPill
                            key={groupType}
                            groupType={groupType}
                            universalSearchLogicProps={universalSearchLogicProps}
                            isActive={groupType === openTab}
                            onClick={() => {
                                setActiveTab(groupType)
                                focusInput()
                            }}
                        />
                    )
                })}
            </div>
            <div className={'taxonomic-group-title with-border'}>
                {searchGroups.find((g) => g.type === openTab)?.name || openTab}
            </div>
            {searchGroupTypes.map((groupType) => {
                return (
                    <div key={groupType} style={{ display: groupType === openTab ? 'block' : 'none' }}>
                        <BindLogic
                            logic={searchListLogic}
                            props={{ ...universalSearchLogicProps, listGroupType: groupType }}
                        >
                            <SearchList />
                        </BindLogic>
                    </div>
                )
            })}
        </>
    )
}
