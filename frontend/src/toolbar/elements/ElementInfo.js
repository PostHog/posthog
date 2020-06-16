import React from 'react'
import { useValues } from 'kea'
import { ActionStep } from '~/toolbar/elements/ActionStep'
import { CalendarOutlined, AimOutlined } from '@ant-design/icons'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { Button, Statistic, Row, Col, Divider } from 'antd'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'

export function ElementInfo() {
    const { eventCount } = useValues(heatmapLogic)
    const { hoverElement, hoverElementMeta, selectedElement, selectedElementMeta, hoverElementHighlight } = useValues(
        elementsLogic
    )

    const activeMeta = hoverElementMeta || selectedElementMeta

    if (hoverElementHighlight || !activeMeta) {
        return null
    }

    const pointerEvents = selectedElementMeta && (!hoverElement || hoverElement === selectedElement)
    const { position, count, actionStep } = activeMeta

    return (
        <>
            {position ? (
                <>
                    <p>
                        <CalendarOutlined /> <u>Last 7 days</u>
                    </p>
                    <Row gutter={16}>
                        <Col span={8}>
                            <Statistic title="Ranking" prefix="#" value={position || 0} />
                        </Col>
                        <Col span={16}>
                            <Statistic
                                title="Clicks"
                                value={count || 0}
                                suffix={`/ ${eventCount} (${
                                    eventCount === 0 ? '-' : Math.round(((count || 0) / eventCount) * 10000) / 100
                                }%)`}
                            />
                        </Col>
                    </Row>
                    <Divider />
                </>
            ) : null}

            <ActionStep actionStep={actionStep} />

            <Divider />

            <p>
                <AimOutlined /> Actions
            </p>
            <div style={{ marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid #eee' }}>
                {pointerEvents ? (
                    <div>
                        <Button>Add Action</Button>
                    </div>
                ) : (
                    <div>Click on the element to add an action</div>
                )}
            </div>
        </>
    )
}
