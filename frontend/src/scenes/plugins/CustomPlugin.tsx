import React from 'react'
import { Button, Col, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export function CustomPlugin(): JSX.Element {
    const { customPluginUrl, pluginError, loading } = useValues(pluginsLogic)
    const { setCustomPluginUrl, installPlugin } = useActions(pluginsLogic)

    return (
        <div>
            <h1 className="page-header">Install Custom Plugin</h1>
            <p>
                Paste the URL of the Plugin's <strong>Github Repository</strong> to install it
            </p>

            <Row style={{ maxWidth: 600, width: '100%' }}>
                <Col style={{ flex: 1 }}>
                    <Input
                        value={customPluginUrl}
                        disabled={loading}
                        onChange={(e) => setCustomPluginUrl(e.target.value)}
                        placeholder="https://github.com/user/repo"
                    />
                </Col>
                <Col>
                    <Button
                        disabled={loading}
                        loading={loading}
                        type="primary"
                        onClick={() => installPlugin(customPluginUrl, true)}
                    >
                        Install
                    </Button>
                </Col>
            </Row>
            {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
        </div>
    )
}
