import React from 'react'
import { hot } from 'react-hot-loader/root'
import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ToolbarContent } from '~/toolbar/ToolbarContent'
import { ToolbarTabs } from '~/toolbar/ToolbarTabs'
import { FloatingToolbarHeader } from '~/toolbar/shared/FloatingToolbarHeader'

export const Toolbar = hot(_Toolbar)
function _Toolbar({ apiURL, temporaryToken, actionId, type, dockLogic }) {
    const { tab, newTab } = useValues(toolbarLogic)

    const visible = tab ? { [tab]: 'visible' } : {}
    const invisible = newTab && tab ? { [newTab]: 'invisible' } : {}
    const fadingOut = newTab && tab ? { [tab]: 'fading-out' } : {}
    const fadingIn = newTab && !tab ? { [newTab]: 'fading-in' } : {}

    // This creates three different tabs, rendering each one when needed as directed by the animation logic

    return (
        <div>
            {type === 'floating' ? <FloatingToolbarHeader dockLogic={dockLogic} /> : null}
            <ToolbarTabs type={type} />
            <div className="toolbar-transition-area">
                {['stats', 'actions', 'dashboards'].map(key => {
                    const className = fadingOut[key] || fadingIn[key] || invisible[key] || visible[key]
                    if (className) {
                        return (
                            <ToolbarContent
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
