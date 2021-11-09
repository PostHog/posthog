import React from 'react'
import { useActions, useValues } from 'kea'
import { List, Space, Spin } from 'antd'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { getShadowRootPopupContainer } from '~/toolbar/utils'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

export function HeatmapStats(): JSX.Element {
    const { countedElements, clickCount, heatmapEnabled, heatmapLoading, heatmapFilter } = useValues(heatmapLogic)
    const { setHeatmapFilter } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    return (
        <div style={{ margin: 8 }}>
            {heatmapEnabled ? (
                <>
                    <div style={{ marginTop: 0, marginBottom: 10 }}>
                        <DateFilter
                            defaultValue="Last 7 days"
                            dateFrom={heatmapFilter.date_from}
                            dateTo={heatmapFilter.date_to}
                            onChange={(date_from, date_to) => setHeatmapFilter({ date_from, date_to })}
                            getPopupContainer={getShadowRootPopupContainer}
                        />
                        {heatmapLoading ? <Spin style={{ marginLeft: 8 }} /> : null}
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
