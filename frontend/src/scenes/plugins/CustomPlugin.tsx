import React from 'react'
import { Button, Card, Col, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export function CustomPlugin(): JSX.Element {
    const { customPluginUrl, pluginError, loading } = useValues(pluginsLogic)
    const { setCustomPluginUrl, installPlugin } = useActions(pluginsLogic)

    return (
        <div style={{ marginTop: 32 }}>
            <Card>
                <h3 className="l3">Install Custom Plugin</h3>
                <p>
                    To install a third-party or custom plugin, please paste the plugin's repository below.{' '}
                    <b className="text-warning">Warning: Only install plugins from trusted sources.</b>
                </p>

                <Row style={{ width: '100%' }} gutter={16}>
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
                            type="default"
                            onClick={() => installPlugin(customPluginUrl, true)}
                        >
                            Fetch and install
                        </Button>
                    </Col>
                </Row>
                {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
            </Card>
        </div>
    )
}
