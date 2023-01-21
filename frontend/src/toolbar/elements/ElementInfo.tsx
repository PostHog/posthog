import React from 'react'
import { useActions, useValues } from 'kea'
import { ActionStep } from '~/toolbar/elements/ActionStep'
import { CalendarOutlined, PlusOutlined } from '@ant-design/icons'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { Button, Statistic, Row, Col } from 'antd'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'

export function ElementInfo(): JSX.Element | null {
    const { clickCount } = useValues(heatmapLogic)

    const { hoverElementMeta, selectedElementMeta } = useValues(elementsLogic)
    const { createAction } = useActions(elementsLogic)
    const { shouldSimplifyActions } = useValues(featureFlagsLogic)

    const activeMeta = hoverElementMeta || selectedElementMeta

    if (!activeMeta) {
        return null
    }

    const { element, position, count, actionStep } = activeMeta

    return (
        <>
            <div style={{ padding: 15, borderLeft: '5px solid #8F98FF', background: 'hsla(235, 100%, 99%, 1)' }}>
                <h1 className="section-title">Selected Element</h1>
                <ActionStep actionStep={actionStep} />
            </div>

            {position ? (
                <div style={{ padding: 15, borderLeft: '5px solid #FF9870', background: 'hsla(19, 99%, 99%, 1)' }}>
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
                </div>
            ) : null}

            <div style={{ padding: 15, borderLeft: '5px solid #94D674', background: 'hsla(100, 74%, 98%, 1)' }}>
                <h1 className="section-title">
                    {shouldSimplifyActions ? 'Calculated Events' : 'Actions'} ({activeMeta.actions.length})
                </h1>

                {activeMeta.actions.length === 0 ? (
                    <p>No {shouldSimplifyActions ? 'calculated events' : 'actions'} include this element</p>
                ) : (
                    <ActionsListView actions={activeMeta.actions.map((a) => a.action)} />
                )}

                <Button size="small" onClick={() => createAction(element)}>
                    <PlusOutlined /> Create a new {shouldSimplifyActions ? 'calculated event' : 'action'}
                </Button>
            </div>
        </>
    )
}
