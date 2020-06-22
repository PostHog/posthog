import React, { useState } from 'react'
import { useValues } from 'kea'
import { ActionStep } from '~/toolbar/elements/ActionStep'
import { CalendarOutlined, AimOutlined } from '@ant-design/icons'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { Button, Statistic, Row, Col, Divider } from 'antd'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { NewAction } from '~/toolbar/elements/NewAction'

export function ElementInfo() {
    const { clickCount } = useValues(heatmapLogic)
    const { hoverElement, hoverElementMeta, selectedElement, selectedElementMeta, hoverElementHighlight } = useValues(
        elementsLogic
    )
    const [newAction, setNewAction] = useState(false)

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
                        <Col span={16}>
                            <Statistic
                                title="Clicks"
                                value={count || 0}
                                suffix={`/ ${clickCount} (${
                                    clickCount === 0 ? '-' : Math.round(((count || 0) / clickCount) * 10000) / 100
                                }%)`}
                            />
                        </Col>
                        <Col span={8}>
                            <Statistic title="Ranking" prefix="#" value={position || 0} />
                        </Col>
                    </Row>
                    <Divider />
                </>
            ) : null}

            <ActionStep actionStep={actionStep} />

            <Divider />

            <p>
                <AimOutlined /> {activeMeta.actions.length} Actions
            </p>
            <div style={{ marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid #eee' }}>
                {pointerEvents ? (
                    <div>
                        {newAction ? (
                            <NewAction actionStep={actionStep} />
                        ) : (
                            <Button onClick={() => setNewAction(true)}>New Action</Button>
                        )}
                    </div>
                ) : (
                    <div>Click on the element to add an action</div>
                )}
            </div>
        </>
    )
}
