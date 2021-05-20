import { Drawer } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { DashboardItemType } from '~/types'
import { activityHistoryLogic } from './activityHistoryLogic'

export function ActivityHistory(): JSX.Element {
    const { showActivityHistory, activityHistory } = useValues(activityHistoryLogic)
    const { setShowActivityHistory } = useActions(activityHistoryLogic)

    return (
        <div>
            <Drawer
                title="Activity History"
                width={400}
                onClose={() => setShowActivityHistory(false)}
                visible={showActivityHistory}
            >
                {activityHistory?.length >= 1 &&
                    activityHistory.map((insight: DashboardItemType) => (
                        <ul key={insight.id}>
                            <li>previous name: {insight.name}</li>
                            <li>parent: {insight.parent}</li>
                        </ul>
                    ))}
            </Drawer>
        </div>
    )
}
