import React from 'react'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { List, Button, Space, Spin } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

export function ActionsList() {
    const { allActions, actionsForCurrentUrl, allActionsLoading } = useValues(actionsLogic)

    const { selectAction, newAction } = useActions(actionsTabLogic)
    console.log(actionsForCurrentUrl)
    return (
        <div>
            <Button type="primary" size="small" onClick={newAction} style={{ float: 'right' }}>
                <PlusOutlined /> New Action
            </Button>
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                Actions ({actionsForCurrentUrl.length})
            </h1>

            {allActions.length === 0 && allActionsLoading ? (
                <Spin />
            ) : (
                <List
                    itemLayout="horizontal"
                    dataSource={actionsForCurrentUrl}
                    renderItem={(action, index) => (
                        <List.Item onClick={() => selectAction(action.id)} style={{ cursor: 'pointer' }}>
                            <List.Item.Meta
                                title={
                                    <Space>
                                        <span
                                            style={{
                                                display: 'inline-block',
                                                width: Math.floor(Math.log10(actionsForCurrentUrl.length) + 1) * 12 + 6,
                                                textAlign: 'right',
                                                marginRight: 4,
                                            }}
                                        >
                                            {index + 1}.
                                        </span>
                                        {action.name || <span style={{ color: '#888' }}>Untitled</span>}
                                    </Space>
                                }
                            />
                        </List.Item>
                    )}
                />
            )}
        </div>
    )
}
