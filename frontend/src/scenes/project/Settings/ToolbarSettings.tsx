import React from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Col, Row, Switch } from 'antd'

/* TODO: This should be moved to user's settings (good first issue) */
export function ToolbarSettings(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
            <Row style={{ flexFlow: 'row' }}>
                <Col>
                    <Switch
                        onChange={() => {
                            updateUser({
                                user: {
                                    toolbar_mode: user?.toolbar_mode === 'disabled' ? 'toolbar' : 'disabled',
                                },
                            })
                        }}
                        defaultChecked={user?.toolbar_mode !== 'disabled'}
                        disabled={userLoading}
                        loading={userLoading}
                    />
                </Col>
                <Col>
                    <label
                        style={{
                            marginLeft: '10px',
                        }}
                    >
                        Enable the PostHog Toolbar, which gives access to heatmaps, stats and allows you to create
                        actions, without ever leaving your own website or app!
                    </label>
                </Col>
            </Row>
        </div>
    )
}
