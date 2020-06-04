import React from 'react'
import { hot } from 'react-hot-loader/root'
import { useValues } from 'kea'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { ToolbarTabs } from '~/toolbar/ToolbarTabs'
import { FloatingToolbarHeader } from '~/toolbar/shared/FloatingToolbarHeader'
import { StatsTab } from '~/toolbar/stats/StatsTab'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { DashboardsTab } from '~/toolbar/dashboards/DashboardsTab'

const tabComponents = {
    actions: ActionsTab,
    stats: StatsTab,
    dashboards: DashboardsTab,
}

export const ToolbarContent = hot(_ToolbarContent)
function _ToolbarContent({ apiURL, temporaryToken, actionId, type, dockLogic }) {
    const { tab, newTab } = useValues(toolbarTabLogic)

    const visible = tab ? { [tab]: 'visible' } : {}
    const invisible = newTab && tab ? { [newTab]: 'invisible' } : {}
    const fadingOut = newTab && tab ? { [tab]: 'fading-out' } : {}
    const fadingIn = newTab && !tab ? { [newTab]: 'fading-in' } : {}

    // This creates three different tabs, rendering each one when needed as directed by the animation logic

    return (
        <div>
            {type === 'float' ? <FloatingToolbarHeader dockLogic={dockLogic} /> : null}
            <ToolbarTabs type={type} />
            <div className="toolbar-transition-area">
                {['stats', 'actions', 'dashboards'].map(key => {
                    const className = fadingOut[key] || fadingIn[key] || invisible[key] || visible[key]
                    if (className) {
                        const Tab = tabComponents[key]
                        return (
                            <Tab
                                key={key}
                                tab={key}
                                type={type}
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
