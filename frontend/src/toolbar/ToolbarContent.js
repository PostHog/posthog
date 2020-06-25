import React from 'react'
import { hot } from 'react-hot-loader/root'
import { useActions, useValues } from 'kea'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { ToolbarTabs } from '~/toolbar/ToolbarTabs'
import { StatsTab } from '~/toolbar/stats/StatsTab'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ElementInfo } from '~/toolbar/elements/ElementInfo'
import { Button } from 'antd'
import { dockLogic } from '~/toolbar/dockLogic'
import { CloseOutlined, InsertRowRightOutlined } from '@ant-design/icons'

export const ToolbarContent = hot(_ToolbarContent)
function _ToolbarContent({ type }) {
    const { tab } = useValues(toolbarTabLogic)
    const { hoverElement, selectedElement, inspectEnabled, heatmapEnabled } = useValues(elementsLogic)
    const { setSelectedElement } = useActions(elementsLogic)
    const { button, dock } = useActions(dockLogic)

    const showElementInsteadOfTabs =
        type === 'dock' && tab === 'stats' && (inspectEnabled || heatmapEnabled) && (hoverElement || selectedElement)

    return (
        <div>
            {showElementInsteadOfTabs ? (
                <>
                    <div style={{ height: 66, lineHeight: '56px' }}>
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
                <div>
                    {type === 'float' ? (
                        <div style={{ textAlign: 'right' }}>
                            <Button onClick={dock}>
                                Dock <InsertRowRightOutlined />
                            </Button>
                            <Button onClick={button}>
                                Close <CloseOutlined />
                            </Button>
                        </div>
                    ) : null}
                    <ToolbarTabs type={type} />
                    {tab === 'stats' ? <StatsTab /> : null}
                    {tab === 'actions' ? <ActionsTab /> : null}
                </div>
            )}
        </div>
    )
}
