import React from 'react'
import { Actions } from '~/editor/Actions'
import { Tabs } from 'antd'
import { kea, useActions, useValues } from 'kea'

const { TabPane } = Tabs

export const toolbarLogic = kea({
    actions: () => ({
        setSection: section => ({ section }),
    }),
    reducers: () => ({
        section: [
            'stats',
            {
                setSection: (_, { section }) => section,
            },
        ],
    }),
})

export function Toolbar({ apiURL, temporaryToken, actionId }) {
    const { section } = useValues(toolbarLogic)
    const { setSection } = useActions(toolbarLogic)

    return (
        <div>
            <Tabs defaultActiveKey={section} onChange={setSection}>
                <TabPane tab={<>Stats</>} key="stats">
                    Content of Tab Pane 1
                </TabPane>
                <TabPane tab={<>Actions</>} key="actions">
                    <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
                </TabPane>
                <TabPane tab={<>Dashboards</>} key="dashboards">
                    Content of Tab Pane 3
                </TabPane>
            </Tabs>
        </div>
    )
}
