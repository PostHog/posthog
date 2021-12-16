import React from 'react'
import { Tag } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import clsx from 'clsx'

export interface InfiniteSelectResultsProps {
    focusInput: () => void
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}

function CategoryPill({
    isActive,
    groupType,
    taxonomicFilterLogicProps,
    onClick,
}: {
    isActive: boolean
    groupType: TaxonomicFilterGroupType
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    onClick: () => void
}): JSX.Element {
    const logic = infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: groupType })
    const { taxonomicGroups } = useValues(taxonomicFilterLogic)
    const { totalCount } = useValues(logic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    return (
        <Tag
            data-attr={`taxonomic-tab-${groupType}`}
            className={clsx({ 'taxonomic-pill-active': isActive, 'taxonomic-count-zero': totalCount === 0 })}
            onClick={totalCount > 0 ? onClick : undefined}
        >
            {group?.name}: {totalCount || 0}
        </Tag>
    )
}

export function InfiniteSelectResults({
    focusInput,
    taxonomicFilterLogicProps,
}: InfiniteSelectResultsProps): JSX.Element {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes } = useValues(taxonomicFilterLogic)
    const { setActiveTab } = useActions(taxonomicFilterLogic)

    if (taxonomicGroupTypes.length === 1) {
        return (
            <BindLogic
                logic={infiniteListLogic}
                props={{ ...taxonomicFilterLogicProps, listGroupType: taxonomicGroupTypes[0] }}
            >
                <InfiniteList />
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
                            taxonomicFilterLogicProps={taxonomicFilterLogicProps}
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
                            logic={infiniteListLogic}
                            props={{ ...taxonomicFilterLogicProps, listGroupType: groupType }}
                        >
                            <InfiniteList />
                        </BindLogic>
                    </div>
                )
            })}
        </>
    )
}
