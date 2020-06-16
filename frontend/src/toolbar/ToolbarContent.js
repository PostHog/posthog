import React from 'react'
import { hot } from 'react-hot-loader/root'
import { useActions, useValues } from 'kea'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { ToolbarTabs } from '~/toolbar/ToolbarTabs'
import { FloatingToolbarHeader } from '~/toolbar/shared/FloatingToolbarHeader'
import { StatsTab } from '~/toolbar/stats/StatsTab'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { DashboardsTab } from '~/toolbar/dashboards/DashboardsTab'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ElementInfo } from '~/toolbar/elements/ElementInfo'
import { Button } from 'antd'

const tabComponents = {
    actions: ActionsTab,
    stats: StatsTab,
    dashboards: DashboardsTab,
}

export const ToolbarContent = hot(_ToolbarContent)
function _ToolbarContent({ type }) {
    const { tab, newTab } = useValues(toolbarTabLogic)
    const { hoverElement, selectedElement } = useValues(elementsLogic)
    const { setSelectedElement } = useActions(elementsLogic)

    const visible = tab ? { [tab]: 'visible' } : {}
    const invisible = newTab && tab ? { [newTab]: 'invisible' } : {}
    const fadingOut = newTab && tab ? { [tab]: 'fading-out' } : {}
    const fadingIn = newTab && !tab ? { [newTab]: 'fading-in' } : {}

    // This creates three different tabs, rendering each one when needed as directed by the animation logic

    return (
        <div>
            {type === 'float' ? <FloatingToolbarHeader /> : null}
            {type === 'dock' && (hoverElement || selectedElement) ? (
                <>
                    <div style={{ height: 66 }}>
                        {selectedElement && (!hoverElement || hoverElement === selectedElement) ? (
                            <div>
                                <Button type="link" onClick={() => setSelectedElement(null)}>
                                    Select a different element
                                </Button>
                            </div>
                        ) : hoverElement ? (
                            <div>Click on an element to select it!</div>
                        ) : null}
                    </div>
                    <div className="toolbar-block">
                        <ElementInfo />
                    </div>
                </>
            ) : (
                <>
                    <ToolbarTabs type={type} />
                    <div className="toolbar-transition-area">
                        {['stats', 'actions', 'dashboards'].map(key => {
                            const className = fadingOut[key] || fadingIn[key] || invisible[key] || visible[key]
                            if (className) {
                                const Tab = tabComponents[key]
                                return <Tab key={key} type={type} />
                            } else {
                                return null
                            }
                        })}
                    </div>
                </>
            )}
        </div>
    )
}
