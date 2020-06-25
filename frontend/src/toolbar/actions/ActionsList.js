import React from 'react'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { Button, Spin } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'

export function ActionsList() {
    const { allActions, actionsForCurrentUrl, allActionsLoading } = useValues(actionsLogic)

    const { newAction } = useActions(actionsTabLogic)

    return (
        <div className="actions-list">
            <Button type="primary" size="small" onClick={() => newAction()} style={{ float: 'right' }}>
                <PlusOutlined /> New Action
            </Button>
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                Actions ({actionsForCurrentUrl.length})
            </h1>

            {allActions.length === 0 && allActionsLoading ? (
                <Spin />
            ) : (
                <ActionsListView actions={actionsForCurrentUrl} />
            )}
        </div>
    )
}
