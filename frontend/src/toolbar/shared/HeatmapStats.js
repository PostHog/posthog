import React from 'react'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { FireFilled, FireOutlined } from '@ant-design/icons'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'

export function HeatmapStats() {
    const { countedElements, eventCount, heatmapEnabled, heatmapLoading } = useValues(heatmapLogic)
    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    return (
        <div className="toolbar-block">
            <div>
                <Button
                    type={heatmapEnabled ? 'primary' : 'default'}
                    onClick={heatmapEnabled ? disableHeatmap : enableHeatmap}
                    loading={heatmapLoading}
                >
                    {heatmapEnabled ? <FireFilled /> : <FireOutlined />}
                    Enable Heatmap
                </Button>
            </div>
            {heatmapEnabled && !heatmapLoading ? (
                <>
                    Found: {countedElements.length} elements with {eventCount} clicks!
                    {countedElements.map(({ element, count, actionStep }, index) => (
                        <div
                            key={index}
                            onClick={() => setSelectedElement(element)}
                            onMouseEnter={() => setHighlightElement(element)}
                            onMouseLeave={() => setHighlightElement(null)}
                            style={{ cursor: 'pointer' }}
                        >
                            {index + 1}. {actionStep.text} - {count} clicks
                        </div>
                    ))}
                </>
            ) : null}
        </div>
    )
}
