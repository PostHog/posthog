import React from 'react'
import { Tabs, Tag } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'

export interface InfiniteSelectResultsProps {
    focusInput: () => void
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}

function TabTitle({
    groupType,
    taxonomicFilterLogicProps,
}: {
    groupType: TaxonomicFilterGroupType
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}): JSX.Element {
    const logic = infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: groupType })
    const { taxonomicGroups } = useValues(taxonomicFilterLogic)
    const { totalCount } = useValues(logic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    return (
        <div data-attr={`taxonomic-tab-${groupType}`}>
            {group?.name} {totalCount != null && <Tag>{totalCount}</Tag>}
        </div>
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

    return (
        <Tabs
            activeKey={activeTab || taxonomicGroups[0].type}
            onChange={(value) => {
                setActiveTab(value as TaxonomicFilterGroupType)
                focusInput()
            }}
            tabPosition="top"
            animated={false}
        >
            {taxonomicGroupTypes.map((groupType) => {
                return (
                    <Tabs.TabPane
                        key={groupType}
                        tab={<TabTitle groupType={groupType} taxonomicFilterLogicProps={taxonomicFilterLogicProps} />}
                    >
                        <BindLogic
                            logic={infiniteListLogic}
                            props={{ ...taxonomicFilterLogicProps, listGroupType: groupType }}
                        >
                            <InfiniteList />
                        </BindLogic>
                    </Tabs.TabPane>
                )
            })}
        </Tabs>
    )
}
