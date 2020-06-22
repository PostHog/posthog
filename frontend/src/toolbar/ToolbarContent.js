import React from 'react'
import { hot } from 'react-hot-loader/root'
import { useActions, useValues } from 'kea'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { ToolbarTabs } from '~/toolbar/ToolbarTabs'
import { FloatingToolbarHeader } from '~/toolbar/shared/FloatingToolbarHeader'
import { StatsTab } from '~/toolbar/stats/StatsTab'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ElementInfo } from '~/toolbar/elements/ElementInfo'
import { Button } from 'antd'

export const ToolbarContent = hot(_ToolbarContent)
function _ToolbarContent({ type }) {
    const { tab } = useValues(toolbarTabLogic)
    const { hoverElement, selectedElement } = useValues(elementsLogic)
    const { setSelectedElement } = useActions(elementsLogic)

    // This creates two different tabs, rendering each one when needed as directed by the animation logic

    return (
        <div>
            {type === 'float' ? <FloatingToolbarHeader /> : null}
            {type === 'dock' && tab === 'stats' && (hoverElement || selectedElement) ? (
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
                    {tab === 'stats' ? <StatsTab /> : null}
                    {tab === 'actions' ? <ActionsTab /> : null}
                </>
            )}
        </div>
    )
}
