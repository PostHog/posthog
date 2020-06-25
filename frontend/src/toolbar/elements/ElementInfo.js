import React from 'react'
import { useActions, useValues } from 'kea'
import { ActionStep } from '~/toolbar/elements/ActionStep'
import { CalendarOutlined, PlusOutlined } from '@ant-design/icons'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { Button, Statistic, Row, Col, Divider } from 'antd'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'

export function ElementInfo() {
    const { clickCount } = useValues(heatmapLogic)

    const { hoverElementMeta, selectedElementMeta, hoverElementHighlight } = useValues(elementsLogic)
    const { createAction } = useActions(elementsLogic)

    const activeMeta = hoverElementMeta || selectedElementMeta

    if (hoverElementHighlight || !activeMeta) {
        return null
    }

    const { element, position, count, actionStep } = activeMeta

    return (
        <>
            <h1 className="section-title">Selected Element</h1>
            <ActionStep actionStep={actionStep} />

            <Divider />

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

            <h1 className="section-title">Actions ({activeMeta.actions.length})</h1>

            {activeMeta.actions.length === 0 ? (
                <p>No actions include this element</p>
            ) : (
                <ActionsListView actions={activeMeta.actions.map(a => a.action)} />
            )}

            <Button size="small" onClick={() => createAction(element)}>
                <PlusOutlined /> Create a new action
            </Button>
        </>
    )
}
