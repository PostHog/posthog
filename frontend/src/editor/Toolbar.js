import React from 'react'
import { Actions } from '~/editor/Actions'
import { CurrentPage } from '~/editor/CurrentPage'
import { PageViewStats } from '~/editor/PageViewStats'
import { InspectElement } from '~/editor/InspectElement'
import { hot } from 'react-hot-loader/root'
import { Tabs } from 'antd'
import { kea, useActions, useValues } from 'kea'

const toolbarLogic = kea({
    actions: () => ({
        setTab: tab => ({ tab }),
        removeOldTab: true,
        removeNewTab: tab => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                removeOldTab: () => null,
                removeNewTab: (_, { tab }) => tab,
            },
        ],
        newTab: [
            null,
            {
                setTab: (_, { tab }) => tab,
                removeNewTab: () => null,
            },
        ],
    }),
    listeners: ({ actions }) => ({
        setTab: async ({ tab }, breakpoint) => {
            await breakpoint(200)
            actions.removeOldTab()
            await breakpoint(200)
            actions.removeNewTab(tab)
        },
    }),
})

function ToolbarContent({ tab, apiURL, temporaryToken, actionId, className }) {
    return (
        <div className={`toolbar-content ${className}`}>
            {tab === 'stats' ? <CurrentPage /> : null}
            {tab === 'actions' || tab === 'stats' ? <InspectElement /> : null}
            {tab === 'actions' || tab === 'stats' ? <PageViewStats /> : null}
            {tab === 'actions' ? (
                <div className="float-box">
                    <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
                </div>
            ) : null}
        </div>
    )
}

export const Toolbar = hot(_Toolbar)
function _Toolbar({ apiURL, temporaryToken, actionId }) {
    const { tab, newTab } = useValues(toolbarLogic)
    const { setTab } = useActions(toolbarLogic)

    const visible = tab ? { [tab]: 'visible' } : {}
    const invisible = newTab && tab ? { [newTab]: 'invisible' } : {}
    const fadingOut = newTab && tab ? { [tab]: 'fading-out' } : {}
    const fadingIn = newTab && !tab ? { [newTab]: 'fading-in' } : {}

    return (
        <div>
            <Tabs onChange={setTab} activeKey={newTab || tab}>
                <Tabs.TabPane tab="Stats" key="stats" />
                <Tabs.TabPane tab="Actions" key="actions" />
                <Tabs.TabPane tab="Dashboards" key="dashboards" />
            </Tabs>
            <div className="toolbar-content-area">
                {['stats', 'actions', 'dashboards'].map(key => {
                    const className = fadingOut[key] || fadingIn[key] || invisible[key] || visible[key]
                    if (className) {
                        return (
                            <ToolbarContent
                                key={key}
                                tab={key}
                                apiURL={apiURL}
                                temporaryToken={temporaryToken}
                                actionId={actionId}
                                className={className}
                            />
                        )
                    } else {
                        return null
                    }
                })}
            </div>
        </div>
    )
}
