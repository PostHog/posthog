import React from 'react'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { Button, Spin, Row } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'

export function ActionsList(): JSX.Element {
    const { allActions, sortedActions, allActionsLoading } = useValues(actionsLogic)

    const { newAction } = useActions(actionsTabLogic)

    return (
        <div className="actions-list">
            <Row className="actions-list-header">
                <Button type="primary" size="small" onClick={() => newAction()} style={{ float: 'right' }}>
                    <PlusOutlined /> New Action
                </Button>
            </Row>
            {allActions.length === 0 && allActionsLoading ? <Spin /> : <ActionsListView actions={sortedActions} />}
        </div>
    )
}
