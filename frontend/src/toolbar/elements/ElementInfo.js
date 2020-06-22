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
    const { hoverElementMeta, selectedElementMeta, hoverElementHighlight } = useValues(elementsLogic)
    const [newAction, setNewAction] = useState(false)

    const activeMeta = hoverElementMeta || selectedElementMeta

    if (hoverElementHighlight || !activeMeta) {
        return null
    }

    const { position, count, actionStep } = activeMeta

    return (
        <>
            {position ? (
                <>
                    <h1 className="section-title">Stats</h1>
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

            <h1 className="section-title">Selected Element</h1>
            <ActionStep actionStep={actionStep} />

            <Divider />

            <h1 className="section-title">Actions</h1>

            {activeMeta.actions.length === 0 ? (
                <p>No actions include this element</p>
            ) : (
                <p>
                    <AimOutlined /> {activeMeta.actions.length} Actions
                </p>
            )}
            <div style={{ marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid #eee' }}>
                <div>
                    {newAction ? (
                        <NewAction actionStep={actionStep} />
                    ) : (
                        <Button onClick={() => setNewAction(true)}>Create a new action</Button>
                    )}
                </div>
            </div>
        </>
    )
}
