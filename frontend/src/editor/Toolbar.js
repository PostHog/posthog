import React from 'react'
import { Actions } from '~/editor/Actions'
import { Tabs } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { SearchOutlined } from '@ant-design/icons'
import { CurrentPage } from '~/editor/CurrentPage'

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
                <TabPane tab={<>Stats</>} key="stats" />
                <TabPane tab={<>Actions</>} key="actions" />
                <TabPane tab={<>Dashboards</>} key="dashboards" />
            </Tabs>
            <CurrentPage />
            <div className="float-box button">
                <p>
                    <SearchOutlined /> Inspect an element
                </p>
                <small>Use the inspector select an element on the page and see associated analytics here</small>
            </div>
            <div className="float-box">
                <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
            </div>
        </div>
    )
}
