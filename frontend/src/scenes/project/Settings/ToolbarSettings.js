import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Col, Row, Switch } from 'antd'

export function ToolbarSettings() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            <Row style={{ flexFlow: 'row' }}>
                <Col>
                    <Switch
                        onChange={() => {
                            userUpdateRequest({
                                user: {
                                    toolbar_mode: user.toolbar_mode === 'disabled' ? 'toolbar' : 'disabled',
                                },
                            })
                            setSaved(true)
                        }}
                        defaultChecked={user.toolbar_mode !== 'disabled'}
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
            {saved && (
                <p className="text-success" style={{ marginTop: 10 }}>
                    Preference saved.
                    {user.toolbar_mode !== 'disabled' && <> Please click "Launch Toolbar" in the sidebar!</>}
                </p>
            )}
        </div>
    )
}
