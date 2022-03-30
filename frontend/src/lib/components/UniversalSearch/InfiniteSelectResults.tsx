import React from 'react'
import { Tag } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { universalSearchLogic } from './universalSearchLogic'
import { searchListLogic } from 'lib/components/UniversalSearch/searchListLogic'
import { SearchList } from 'lib/components/UniversalSearch/searchList'
import { UniversalSearchGroupType, UniversalSearchLogicProps } from './types'
import clsx from 'clsx'

export interface InfiniteSelectResultsProps {
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
    const { taxonomicGroups } = useValues(universalSearchLogic)
    const { totalResultCount, totalListCount } = useValues(logic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    // :TRICKY: use `totalListCount` (results + extra) to toggle interactivity, while showing `totalResultCount`
    const canInteract = totalListCount > 0

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

export function InfiniteSelectResults({
    focusInput,
    universalSearchLogicProps,
}: InfiniteSelectResultsProps): JSX.Element {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes } = useValues(universalSearchLogic)
    const { setActiveTab } = useActions(universalSearchLogic)

    if (taxonomicGroupTypes.length === 1) {
        return (
            <BindLogic
                logic={searchListLogic}
                props={{ ...universalSearchLogicProps, listGroupType: taxonomicGroupTypes[0] }}
            >
                <SearchList />
            </BindLogic>
        )
    }

    const openTab = activeTab || taxonomicGroups[0].type
    return (
        <>
            <div className={'taxonomic-group-title'}>Categories</div>
            <div className={'taxonomic-pills'}>
                {taxonomicGroupTypes.map((groupType) => {
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
                {taxonomicGroups.find((g) => g.type === openTab)?.name || openTab}
            </div>
            {taxonomicGroupTypes.map((groupType) => {
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
