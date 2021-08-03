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
                        // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                        id="posthog-toolbar-switch"
                        onChange={() => {
                            updateUser({
                                toolbar_mode: user?.toolbar_mode === 'disabled' ? 'toolbar' : 'disabled',
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
                        htmlFor="posthog-toolbar-switch"
                    >
                        Enable PostHog Toolbar, which gives access to heatmaps, stats and allows you to create actions,
                        right there on your website!
                    </label>
                </Col>
            </Row>
        </div>
    )
}
