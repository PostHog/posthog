import React from 'react'
import { useActions, useValues } from 'kea'
import { Button, List, Space } from 'antd'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { FireFilled, FireOutlined } from '@ant-design/icons'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'

interface HeatmapStatsProps {
    buttonMode?: boolean
}

export function HeatmapStats({ buttonMode = false }: HeatmapStatsProps): JSX.Element {
    const { countedElements, clickCount, heatmapEnabled, heatmapLoading } = useValues(heatmapLogic)
    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    return (
        <div>
            {!buttonMode ? (
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
            ) : null}
            {heatmapEnabled && !heatmapLoading ? (
                <>
                    <div style={{ marginTop: buttonMode ? 0 : 20, marginBottom: 10 }}>
                        <span style={{ borderBottom: '2px dashed hsla(230, 14%, 78%, 1)' }}>Last 7 days</span>
                    </div>
                    <div style={{ marginTop: 20, marginBottom: 10 }}>
                        Found: {countedElements.length} elements / {clickCount} clicks!
                    </div>
                    <List
                        itemLayout="horizontal"
                        dataSource={countedElements}
                        renderItem={({ element, count, actionStep }, index) => (
                            <List.Item
                                onClick={() => setSelectedElement(element)}
                                onMouseEnter={() => setHighlightElement(element)}
                                onMouseLeave={() => setHighlightElement(null)}
                                style={{ cursor: 'pointer' }}
                            >
                                <List.Item.Meta
                                    title={
                                        <Space>
                                            <span
                                                style={{
                                                    display: 'inline-block',
                                                    width: Math.floor(Math.log10(countedElements.length) + 1) * 12 + 6,
                                                    textAlign: 'right',
                                                    marginRight: 4,
                                                }}
                                            >
                                                {index + 1}.
                                            </span>
                                            {actionStep?.text ||
                                                (actionStep?.tag_name ? (
                                                    <code>&lt;{actionStep.tag_name}&gt;</code>
                                                ) : (
                                                    <em>Element</em>
                                                ))}
                                        </Space>
                                    }
                                />
                                <div>{count} clicks</div>
                            </List.Item>
                        )}
                    />
                </>
            ) : null}
        </div>
    )
}
