import React from 'react'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'
import { FireFilled, FireOutlined } from '@ant-design/icons'

export function HeatmapStats() {
    const { countedElements, eventCount, heatmapEnabled, heatmapLoading } = useValues(heatmapLogic)
    const { highlightElement, setHeatmapEnabled } = useActions(heatmapLogic)

    return (
        <div className="toolbar-block">
            <div>
                <Button
                    type={heatmapEnabled ? 'primary' : 'default'}
                    onClick={() => setHeatmapEnabled(!heatmapEnabled)}
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
                            onMouseEnter={() => highlightElement(element, true)}
                            onMouseLeave={() => highlightElement(null)}
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
