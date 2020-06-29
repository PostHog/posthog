import React from 'react'
import { useActions } from 'kea'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { List, Space } from 'antd'

export function ActionsListView({ actions }) {
    const { selectAction } = useActions(actionsTabLogic)
    return (
        <List
            itemLayout="horizontal"
            dataSource={actions}
            renderItem={(action, index) => (
                <List.Item onClick={() => selectAction(action.id)} style={{ cursor: 'pointer' }}>
                    <List.Item.Meta
                        title={
                            <Space>
                                <span
                                    style={{
                                        display: 'inline-block',
                                        width: Math.floor(Math.log10(actions.length) + 1) * 12 + 6,
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
    )
}
