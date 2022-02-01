import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { useValues, useActions } from 'kea'
import { deadLetterQueueLogic, DeadLetterQueueTab } from './deadLetterQueueLogic'
import { userLogic } from 'scenes/userLogic'
import { MetricsTab } from './MetricsTab'

export const scene: SceneExport = {
    component: DeadLetterQueue,
    logic: deadLetterQueueLogic,
}

const { TabPane } = Tabs

export function DeadLetterQueue(): JSX.Element {
    const { user } = useValues(userLogic)
    const { activeTab } = useValues(deadLetterQueueLogic)
    const { setActiveTab } = useActions(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return <></>
    }

    return (
        <div>
            <PageHeader
                title="Dead Letter Queue"
                caption={
                    <>
                        <p>Manage your instance's dead letter queue.</p>
                    </>
                }
            />

            <Tabs activeKey={activeTab} onChange={(key) => setActiveTab(key)}>
                <TabPane tab="Metrics" key={DeadLetterQueueTab.Metrics} />
            </Tabs>

            {activeTab === DeadLetterQueueTab.Metrics ? <MetricsTab /> : null}
        </div>
    )
}
