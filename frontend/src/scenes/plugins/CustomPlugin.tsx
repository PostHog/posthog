import React from 'react'
import { Button, Col, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export function CustomPlugin(): JSX.Element {
    const { customPluginUrl, customPluginError, installingCustomPlugin } = useValues(pluginsLogic)
    const { setCustomPluginUrl, installCustomPlugin } = useActions(pluginsLogic)

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
                        onChange={(e) => setCustomPluginUrl(e.target.value)}
                        placeholder="https://github.com/user/repo"
                    />
                </Col>
                <Col>
                    <Button
                        loading={installingCustomPlugin}
                        type="primary"
                        onClick={() => installCustomPlugin(customPluginUrl)}
                    >
                        Install
                    </Button>
                </Col>
            </Row>
            {customPluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{customPluginError}</p> : null}
        </div>
    )
}
