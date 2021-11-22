import React from 'react'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { Button, Row, Input } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { Spinner } from 'lib/components/Spinner/Spinner'

export function ActionsList(): JSX.Element {
    const { allActions, sortedActions, allActionsLoading, searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)

    const { newAction } = useActions(actionsTabLogic)

    return (
        <>
            <Input.Search
                allowClear
                autoFocus
                placeholder="Search"
                value={searchTerm}
                style={{
                    paddingBottom: '4px',
                }}
                onChange={(e) => setSearchTerm(e.target.value)}
            />
            <div className="actions-list">
                <Row className="actions-list-header">
                    <Button type="primary" size="small" onClick={() => newAction()} style={{ float: 'right' }}>
                        <PlusOutlined /> New Action
                    </Button>
                </Row>
                {true || (allActions.length === 0 && allActionsLoading) ? (
                    <div className="text-center mt mb">
                        <Spinner />
                    </div>
                ) : (
                    <ActionsListView actions={sortedActions} />
                )}
            </div>
        </>
    )
}
