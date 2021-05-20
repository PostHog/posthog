import { Drawer } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { activityHistoryLogic } from './activityHistoryLogic'

export function ActivityHistory(): JSX.Element {
    const { showActivityHistory } = useValues(activityHistoryLogic)
    const { setShowActivityHistory } = useActions(activityHistoryLogic)

    return(
        <div>
            <Drawer
                title="Activity History"
                width={400}
                onClose={() => setShowActivityHistory(false)}
                visible={showActivityHistory}
            >
                <div>?</div>
            </Drawer>
        </div>
    )
}