import { Skeleton, Tabs } from 'antd'
import { useValues, useActions } from 'kea'
import React from 'react'
import { PageHeader } from '../../lib/components/PageHeader'
import { groupsLogic } from './groupsLogic'
import { Groups } from './Groups'
import { capitalizeFirstLetter } from 'lib/utils'

const { TabPane } = Tabs

export function GroupTypes(): JSX.Element {
    const { groupTypes, groupTypesLoading, currentGroupType } = useValues(groupsLogic)
    const { setCurrentGroupType } = useActions(groupsLogic)

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader title="Groups" />

            {groupTypesLoading ? (
                Array(5)
                    .fill(null)
                    .map((_, i) => <Skeleton key={i} active paragraph={false} />)
            ) : (
                <>
                    <Tabs
                        activeKey={currentGroupType || ''}
                        onChange={(tab) => {
                            setCurrentGroupType(tab)
                        }}
                    >
                        {groupTypes.map(({ type_key }) => (
                            <TabPane tab={capitalizeFirstLetter(type_key)} key={type_key} />
                        ))}
                    </Tabs>
                    {currentGroupType ? <Groups /> : null}
                </>
            )}
        </div>
    )
}
